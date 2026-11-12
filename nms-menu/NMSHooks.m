#import "NMSHooks.h"
#import <mach/mach.h>
#import <mach-o/dyld.h>
#import <libkern/OSCacheControl.h>
#import <string.h>

// ARM64 指令编码（补丁用）
//   ret           0xD65F03C0
//   mov w0, #0    0x52800000
//   mov w0, #1    0x52800020
//   fmov s0, wzr  0x1E2703E0
#define INSN_RET        0xD65F03C0u
#define INSN_MOV_W0_0   0x52800000u
#define INSN_MOV_W0_1   0x52800020u
#define INSN_FMOV_S0_0  0x1E2703E0u

typedef struct {
    const char *key;
    const char *title;
    const char *desc;
    uint32_t offset;      // 相对主程序 __TEXT 的文件偏移
    uint64_t patch;       // 新指令（低 4 字节 = 第一条）
    uint64_t expect;      // 原始指令，用于校验
} NMSPatchDef;

// 全部地址来自符号表反混淆，并已核对机器码序言。
// expect 是打补丁前该处的真实 8 字节，版本不一致时校验失败 -> 拒绝打补丁。
static const NMSPatchDef kPatchDefs[] = {
    {
        "jetpack", "无限喷气背包", "GetJetpackDrain() 返回 0，燃料不再消耗",
        0x0df5c5c,
        ((uint64_t)INSN_RET << 32) | INSN_FMOV_S0_0,
        0x910003FDA9BF7BFDULL
    },
    {
        "shipfuel", "无限飞船燃料", "UseTakeOffFuel() 直接返回，起飞不扣燃料",
        0x10a0b10,
        ((uint64_t)INSN_RET << 32) | INSN_RET,
        0x6D0623E9D10283FFULL
    },
    {
        "noitem", "物品不消耗", "InventoryStore::Remove() 直接返回成功",
        0x02a18f8,
        ((uint64_t)INSN_RET << 32) | INSN_MOV_W0_1,
        0xA90157F6D10103FFULL
    },
    {
        "godmode", "无敌（玩家伤害）", "cGcPlayer::TakeDamage() 直接返回 false",
        0x0e13870,
        ((uint64_t)INSN_RET << 32) | INSN_MOV_W0_0,
        0xA9014FF4D100C3FFULL
    },
};
static const size_t kPatchCount = sizeof(kPatchDefs) / sizeof(kPatchDefs[0]);

static NSString *const kPrefKey = @"com.seagull.nmsmenu.patchStates";

static uint8_t *gBase = NULL;
static NSMutableDictionary<NSString *, NSNumber *> *gOriginals = nil;

@implementation NMSHooks

+ (void)nms_ensureInit
{
    // 延迟初始化：不在 +load / 构造函数里创建 ObjC 对象，避免加载顺序问题
    if (!gBase) gBase = (uint8_t *)_dyld_get_image_header(0);
    if (!gOriginals) gOriginals = [NSMutableDictionary dictionary];
}

+ (uint64_t)mainBase
{
    [self nms_ensureInit];
    return (uint64_t)gBase;
}

+ (const NMSPatchDef *)defForKey:(NSString *)key
{
    for (size_t i = 0; i < kPatchCount; i++) {
        if ([key isEqualToString:[NSString stringWithUTF8String:kPatchDefs[i].key]]) {
            return &kPatchDefs[i];
        }
    }
    return NULL;
}

+ (NSDictionary *)stateDict
{
    NSDictionary *d = [[NSUserDefaults standardUserDefaults] dictionaryForKey:kPrefKey];
    return d ?: @{};
}

+ (void)saveState:(NSString *)key on:(BOOL)on
{
    NSMutableDictionary *d = [[self stateDict] mutableCopy];
    d[key] = @(on);
    [[NSUserDefaults standardUserDefaults] setObject:d forKey:kPrefKey];
}

+ (BOOL)isOn:(NSString *)key
{
    return [[self stateDict][key] boolValue];
}

+ (NSArray<NSDictionary *> *)allPatches
{
    NSMutableArray *out = [NSMutableArray array];
    for (size_t i = 0; i < kPatchCount; i++) {
        NSString *key = [NSString stringWithUTF8String:kPatchDefs[i].key];
        [out addObject:@{
            @"key": key,
            @"title": [NSString stringWithUTF8String:kPatchDefs[i].title],
            @"desc": [NSString stringWithUTF8String:kPatchDefs[i].desc],
            @"enabled": @([self isOn:key]),
        }];
    }
    return out;
}

+ (BOOL)writeCode:(void *)addr value:(uint64_t)value
{
    vm_size_t ps = vm_page_size ? vm_page_size : 16384;
    uintptr_t start = (uintptr_t)addr;
    uintptr_t first = start & ~(uintptr_t)(ps - 1);
    uintptr_t last  = (start + 8 - 1) & ~(uintptr_t)(ps - 1);
    vm_size_t span  = (vm_size_t)(last - first) + ps;

    kern_return_t kr = vm_protect(mach_task_self(), (vm_address_t)first, span, NO,
                                  VM_PROT_READ | VM_PROT_WRITE | VM_PROT_COPY);
    if (kr != KERN_SUCCESS) {
        NSLog(@"[NMSMenu] vm_protect(rw) 失败: %d", kr);
        return NO;
    }
    memcpy(addr, &value, 8);
    sys_icache_invalidate(addr, 8);
    vm_protect(mach_task_self(), (vm_address_t)first, span, NO,
               VM_PROT_READ | VM_PROT_EXECUTE);
    return YES;
}

+ (BOOL)setPatch:(NSString *)key enabled:(BOOL)enabled
{
    const NMSPatchDef *def = [self defForKey:key];
    if (!def) return NO;
    [self nms_ensureInit];
    if (!gBase) return NO;

    uint8_t *addr = gBase + def->offset;
    uint64_t cur = 0;
    memcpy(&cur, addr, 8);

    if (enabled) {
        if (cur == def->patch) {           // 已经是补丁状态
            [self saveState:key on:YES];
            return YES;
        }
        if (cur != def->expect) {          // 版本不匹配，拒绝
            NSLog(@"[NMSMenu] %s 原始字节不匹配: 期望 %llx 实际 %llx",
                  def->key, def->expect, cur);
            return NO;
        }
        gOriginals[key] = @(cur);
        BOOL ok = [self writeCode:addr value:def->patch];
        if (ok) [self saveState:key on:YES];
        return ok;
    } else {
        if (cur == def->expect) {          // 已经是原始状态
            [self saveState:key on:NO];
            return YES;
        }
        uint64_t orig = gOriginals[key] ? gOriginals[key].unsignedLongLongValue : def->expect;
        BOOL ok = [self writeCode:addr value:orig];
        if (ok) [self saveState:key on:NO];
        return ok;
    }
}

+ (void)restoreAll
{
    NSDictionary *d = [self stateDict];
    for (NSString *key in d) {
        if ([d[key] boolValue]) {
            [self setPatch:key enabled:YES];
        }
    }
}

@end
