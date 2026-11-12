#import "NMSCheatEngine.h"
#import <mach/mach.h>
#import <mach/mach_vm.h>
#import <mach/vm_region.h>

// 单段最多扫 64MB，总量最多 2GB，避免卡死
static const uint64_t kMaxRegionSize = 64ull << 20;
static const uint64_t kMaxTotalBytes = 2ull << 30;
// 冻结列表上限
static const NSUInteger kMaxFreeze = 512;

@interface NMSCheatEngine () {
    NSMutableArray<NSNumber *> *_addrs;
    NSMutableArray<NSNumber *> *_last;
    NSMutableArray<NSNumber *> *_frozenAddrs;
    int32_t _frozenValue;
    dispatch_source_t _freezeTimer;
}
@property (nonatomic, readwrite) NSUInteger scannedRegions;
@property (nonatomic, readwrite) uint64_t scannedBytes;
@end

@implementation NMSCheatEngine

+ (instancetype)shared
{
    static NMSCheatEngine *e;
    static dispatch_once_t once;
    dispatch_once(&once, ^{ e = [NMSCheatEngine new]; });
    return e;
}

- (instancetype)init
{
    if ((self = [super init])) {
        _addrs = [NSMutableArray array];
        _last = [NSMutableArray array];
        _frozenAddrs = [NSMutableArray array];
    }
    return self;
}

- (NSUInteger)resultCount { return _addrs.count; }
- (BOOL)frozen { return _freezeTimer != NULL; }

- (void)clear
{
    [_addrs removeAllObjects];
    [_last removeAllObjects];
}

#pragma mark - 内存基础操作

static BOOL nms_read32(uint64_t addr, int32_t *out)
{
    vm_size_t got = 0;
    kern_return_t kr = vm_read_overwrite(mach_task_self(), (vm_address_t)addr, 4,
                                         (vm_address_t)out, &got);
    return kr == KERN_SUCCESS && got == 4;
}

static BOOL nms_write32(uint64_t addr, int32_t value)
{
    vm_address_t page = (vm_address_t)(addr & ~(uint64_t)(vm_page_size - 1));
    vm_protect(mach_task_self(), page, vm_page_size, NO,
               VM_PROT_READ | VM_PROT_WRITE | VM_PROT_COPY);
    return vm_write(mach_task_self(), (vm_address_t)addr,
                    (vm_offset_t)&value, 4) == KERN_SUCCESS;
}

/// 遍历本进程所有可读可写的私有段
static void nms_enumerate_rw(void (^block)(uint64_t addr, uint64_t size))
{
    mach_vm_address_t address = 0;
    mach_vm_size_t size = 0;
    natural_t depth = 0;

    while (YES) {
        struct vm_region_submap_info_64 info;
        mach_msg_type_number_t count = VM_REGION_SUBMAP_INFO_COUNT_64;
        kern_return_t kr = vm_region_recurse_64(mach_task_self(), &address, &size, &depth,
                                                (vm_region_recurse_info_t)&info, &count);
        if (kr != KERN_SUCCESS) break;

        if (info.is_submap) {
            depth++;
            continue;
        }

        vm_prot_t p = info.protection;
        BOOL ok = (p & VM_PROT_READ) && (p & VM_PROT_WRITE) && !(p & VM_PROT_EXECUTE);
        if (ok && size > 0) {
            block(address, size);
        }
        address += size;
    }
}

#pragma mark - 扫描

- (NSUInteger)firstScan:(int32_t)value
{
    [self clear];
    self.scannedRegions = 0;
    self.scannedBytes = 0;

    __block uint64_t total = 0;
    nms_enumerate_rw(^(uint64_t addr, uint64_t size) {
        if (total >= kMaxTotalBytes) return;
        uint64_t len = MIN(size, kMaxRegionSize);
        if (len < 4) return;

        void *buf = malloc((size_t)len);
        if (!buf) return;
        vm_size_t got = 0;
        kern_return_t kr = vm_read_overwrite(mach_task_self(), (vm_address_t)addr,
                                             (vm_size_t)len, (vm_address_t)buf, &got);
        if (kr != KERN_SUCCESS) { free(buf); return; }

        total += got;
        self.scannedRegions += 1;
        self.scannedBytes = total;

        const int32_t *p = (const int32_t *)buf;
        uint64_t n = got / 4;
        for (uint64_t i = 0; i < n; i++) {
            if (p[i] == value) {
                [self->_addrs addObject:@(addr + i * 4)];
            }
        }
        free(buf);
    });

    // 记录当前值，供"变大/变小/变动"过滤用
    NSMutableArray *vals = [NSMutableArray arrayWithCapacity:_addrs.count];
    for (NSNumber *a in _addrs) {
        int32_t v = 0;
        nms_read32(a.unsignedLongLongValue, &v);
        [vals addObject:@(v)];
    }
    _last = vals;
    return _addrs.count;
}

- (NSUInteger)filterExact:(int32_t)value
{
    NSMutableArray *keepA = [NSMutableArray array];
    NSMutableArray *keepV = [NSMutableArray array];
    for (NSUInteger i = 0; i < _addrs.count; i++) {
        int32_t v = 0;
        if (!nms_read32(_addrs[i].unsignedLongLongValue, &v)) continue;
        if (v == value) {
            [keepA addObject:_addrs[i]];
            [keepV addObject:@(v)];
        }
    }
    _addrs = keepA;
    _last = keepV;
    return _addrs.count;
}

- (NSUInteger)filterMode:(NMSFilterMode)mode
{
    NSMutableArray *keepA = [NSMutableArray array];
    NSMutableArray *keepV = [NSMutableArray array];
    for (NSUInteger i = 0; i < _addrs.count; i++) {
        int32_t v = 0;
        if (!nms_read32(_addrs[i].unsignedLongLongValue, &v)) continue;
        int32_t old = (i < _last.count) ? _last[i].intValue : v;
        BOOL keep = NO;
        switch (mode) {
            case NMSFilterChanged:   keep = (v != old); break;
            case NMSFilterUnchanged: keep = (v == old); break;
            case NMSFilterIncreased: keep = (v > old);  break;
            case NMSFilterDecreased: keep = (v < old);  break;
        }
        if (keep) {
            [keepA addObject:_addrs[i]];
            [keepV addObject:@(v)];
        }
    }
    _addrs = keepA;
    _last = keepV;
    return _addrs.count;
}

- (NSArray<NSDictionary *> *)topResults:(NSUInteger)limit
{
    NSMutableArray *out = [NSMutableArray array];
    NSUInteger n = MIN(limit, _addrs.count);
    for (NSUInteger i = 0; i < n; i++) {
        int32_t v = 0;
        nms_read32(_addrs[i].unsignedLongLongValue, &v);
        [out addObject:@{ @"addr": _addrs[i], @"value": @(v) }];
    }
    return out;
}

#pragma mark - 写入

- (NSUInteger)writeAll:(int32_t)value
{
    NSUInteger n = 0;
    for (NSNumber *a in _addrs) {
        if (nms_write32(a.unsignedLongLongValue, value)) n++;
    }
    return n;
}

- (BOOL)writeAt:(uint64_t)addr value:(int32_t)value
{
    return nms_write32(addr, value);
}

#pragma mark - 冻结

- (void)setFreeze:(BOOL)freeze value:(int32_t)value
{
    [_frozenAddrs removeAllObjects];
    if (_freezeTimer) {
        dispatch_source_cancel(_freezeTimer);
        _freezeTimer = nil;
    }
    if (!freeze) return;

    _frozenValue = value;
    NSUInteger n = MIN(_addrs.count, kMaxFreeze);
    for (NSUInteger i = 0; i < n; i++) {
        [_frozenAddrs addObject:_addrs[i]];
    }
    if (_frozenAddrs.count == 0) return;

    _freezeTimer = dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER, 0, 0,
                                          dispatch_get_global_queue(QOS_CLASS_UTILITY, 0));
    dispatch_source_set_timer(_freezeTimer,
                              dispatch_time(DISPATCH_TIME_NOW, 100 * NSEC_PER_MSEC),
                              100 * NSEC_PER_MSEC, 20 * NSEC_PER_MSEC);
    __weak typeof(self) weakSelf = self;
    dispatch_source_set_event_handler(_freezeTimer, ^{
        __strong typeof(self) s = weakSelf;
        if (!s) return;
        for (NSNumber *a in s->_frozenAddrs) {
            nms_write32(a.unsignedLongLongValue, s->_frozenValue);
        }
    });
    dispatch_resume(_freezeTimer);
}

@end
