#import "NMSSaveTool.h"
#import <zlib.h>

static NSString *const kErrDomain = @"NMSMenu.Save";

static NSError *nms_err(NSInteger code, NSString *msg)
{
    return [NSError errorWithDomain:kErrDomain code:code
                           userInfo:@{NSLocalizedDescriptionKey: msg}];
}

#pragma mark - zlib

/// 找到 zlib 流的起始位置（跳过 4~16 字节的存档头部）
static NSInteger nms_zlib_offset(NSData *data)
{
    const uint8_t *b = data.bytes;
    NSUInteger n = MIN(data.length, (NSUInteger)64);
    for (NSUInteger i = 0; i + 1 < n; i++) {
        if (b[i] == 0x78 && (b[i + 1] == 0x01 || b[i + 1] == 0x5E ||
                             b[i + 1] == 0x9C || b[i + 1] == 0xDA)) {
            return (NSInteger)i;
        }
    }
    return -1;
}

static NSData *nms_inflate(NSData *in, NSError **error)
{
    z_stream s;
    memset(&s, 0, sizeof(s));
    if (inflateInit(&s) != Z_OK) {
        if (error) *error = nms_err(1, @"inflateInit 失败");
        return nil;
    }
    s.next_in = (Bytef *)in.bytes;
    s.avail_in = (uInt)in.length;

    NSMutableData *out = [NSMutableData data];
    uint8_t buf[64 * 1024];
    int ret = Z_OK;
    while (ret != Z_STREAM_END) {
        s.next_out = buf;
        s.avail_out = sizeof(buf);
        ret = inflate(&s, Z_NO_FLUSH);
        if (ret != Z_OK && ret != Z_STREAM_END) {
            inflateEnd(&s);
            if (error) *error = nms_err(2, [NSString stringWithFormat:@"inflate 失败 code=%d", ret]);
            return nil;
        }
        [out appendBytes:buf length:sizeof(buf) - s.avail_out];
    }
    inflateEnd(&s);
    return out;
}

static NSData *nms_deflate(NSData *in, NSError **error)
{
    uLongf cap = compressBound((uLong)in.length);
    NSMutableData *out = [NSMutableData dataWithLength:cap];
    int ret = compress2(out.mutableBytes, &cap, in.bytes, (uLong)in.length, 9);
    if (ret != Z_OK) {
        if (error) *error = nms_err(3, @"compress2 失败");
        return nil;
    }
    out.length = cap;
    return out;
}

#pragma mark - JSON 遍历

static BOOL nms_set_stat_in_node(id node, NSString *stat, long long value)
{
    if ([node isKindOfClass:[NSDictionary class]]) {
        NSMutableDictionary *d = node;
        id sid = d[@"Id"];
        if ([sid isKindOfClass:[NSString class]] && [sid isEqualToString:stat]) {
            id v = d[@"Value"];
            if ([v isKindOfClass:[NSDictionary class]]) {
                NSMutableDictionary *vd = v;
                if (vd[@"FloatValue"]) vd[@"FloatValue"] = @((double)value);
                else vd[@"IntValue"] = @(value);
                return YES;
            }
            d[@"Value"] = @{ @"IntValue": @(value) };
            return YES;
        }
        for (id k in [d allKeys]) {
            if (nms_set_stat_in_node(d[k], stat, value)) return YES;
        }
    } else if ([node isKindOfClass:[NSArray class]]) {
        for (id v in node) {
            if (nms_set_stat_in_node(v, stat, value)) return YES;
        }
    }
    return NO;
}

static void nms_collect_stats(id node, NSMutableDictionary *out)
{
    if ([node isKindOfClass:[NSDictionary class]]) {
        NSDictionary *d = node;
        id sid = d[@"Id"];
        id val = d[@"Value"];
        if ([sid isKindOfClass:[NSString class]] && [val isKindOfClass:[NSDictionary class]]) {
            id iv = val[@"IntValue"] ?: val[@"FloatValue"];
            if (iv && !out[sid]) out[sid] = iv;
        }
        for (id k in d) nms_collect_stats(d[k], out);
    } else if ([node isKindOfClass:[NSArray class]]) {
        for (id v in node) nms_collect_stats(v, out);
    }
}

#pragma mark -

@implementation NMSSaveTool

+ (NSString *)documentsPath
{
    return [NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES) firstObject];
}

+ (NSArray<NSString *> *)saveFiles
{
    NSString *dir = [self documentsPath];
    NSArray *all = [[NSFileManager defaultManager] contentsOfDirectoryAtPath:dir error:nil];
    NSMutableArray *out = [NSMutableArray array];
    for (NSString *n in all) {
        if ([n.pathExtension.lowercaseString isEqualToString:@"hg"]) {
            [out addObject:[dir stringByAppendingPathComponent:n]];
        }
    }
    return [out sortedArrayUsingSelector:@selector(compare:)];
}

+ (NSDictionary *)loadJSON:(NSString *)path error:(NSError **)error
{
    NSData *raw = [NSData dataWithContentsOfFile:path options:0 error:error];
    if (!raw) return nil;
    NSInteger off = nms_zlib_offset(raw);
    if (off < 0) {
        if (error) *error = nms_err(4, @"不是有效的 .hg 存档（找不到 zlib 流）");
        return nil;
    }
    NSData *payload = nms_inflate([raw subdataWithRange:NSMakeRange(off, raw.length - off)], error);
    if (!payload) return nil;
    id json = [NSJSONSerialization JSONObjectWithData:payload options:0 error:error];
    if (![json isKindOfClass:[NSDictionary class]]) {
        if (error) *error = nms_err(5, @"JSON 解析失败");
        return nil;
    }
    return json;
}

+ (BOOL)writeJSON:(NSDictionary *)json to:(NSString *)path error:(NSError **)error
{
    NSData *raw = [NSData dataWithContentsOfFile:path options:0 error:nil];
    NSInteger off = raw ? nms_zlib_offset(raw) : -1;
    NSData *prefix = (off > 0) ? [raw subdataWithRange:NSMakeRange(0, off)] : [NSData data];

    NSData *payload = [NSJSONSerialization dataWithJSONObject:json options:0 error:error];
    if (!payload) return NO;
    NSData *comp = nms_deflate(payload, error);
    if (!comp) return NO;

    NSMutableData *out = [NSMutableData dataWithData:prefix];
    [out appendData:comp];
    return [out writeToFile:path options:NSDataWritingAtomic error:error];
}

+ (NSDictionary *)infoForFile:(NSString *)path
{
    NSError *e = nil;
    NSDictionary *json = [self loadJSON:path error:&e];
    if (!json) return @{ @"error": e.localizedDescription ?: @"解析失败" };

    NSDictionary *psd = json[@"PlayerStateData"];
    NSMutableDictionary *stats = [NSMutableDictionary dictionary];
    nms_collect_stats(json, stats);

    NSMutableDictionary *info = [NSMutableDictionary dictionary];
    info[@"file"] = path.lastPathComponent;
    info[@"version"] = json[@"Version"] ?: @0;
    if ([psd isKindOfClass:[NSDictionary class]]) {
        info[@"player"] = psd[@"PlayerName"] ?: @"?";
    }
    info[@"units"] = stats[@"UNITS"] ?: @0;
    info[@"nanites"] = stats[@"NANITES"] ?: @0;
    info[@"statCount"] = @(stats.count);
    return info;
}

+ (BOOL)backupAllWithError:(NSError **)error
{
    NSFileManager *fm = [NSFileManager defaultManager];
    NSDateFormatter *df = [NSDateFormatter new];
    df.dateFormat = @"yyyyMMdd-HHmmss";
    NSString *dir = [[self documentsPath] stringByAppendingPathComponent:
                     [NSString stringWithFormat:@"NMSMenuBackups/%@", [df stringFromDate:[NSDate date]]]];
    if (![fm createDirectoryAtPath:dir withIntermediateDirectories:YES attributes:nil error:error]) return NO;

    NSArray *files = [self saveFiles];
    if (files.count == 0) {
        if (error) *error = nms_err(6, @"没找到 .hg 存档");
        return NO;
    }
    for (NSString *f in files) {
        NSString *dst = [dir stringByAppendingPathComponent:f.lastPathComponent];
        if (![fm copyItemAtPath:f toPath:dst error:error]) return NO;
    }
    return YES;
}

+ (NSString *)latestBackupDir
{
    NSString *base = [[self documentsPath] stringByAppendingPathComponent:@"NMSMenuBackups"];
    NSArray *dirs = [[NSFileManager defaultManager] contentsOfDirectoryAtPath:base error:nil];
    if (dirs.count == 0) return nil;
    NSArray *sorted = [dirs sortedArrayUsingSelector:@selector(compare:)];
    return [base stringByAppendingPathComponent:sorted.lastObject];
}

+ (BOOL)restoreLatestWithError:(NSError **)error
{
    NSString *dir = [self latestBackupDir];
    if (!dir) {
        if (error) *error = nms_err(7, @"没有可用备份");
        return NO;
    }
    NSFileManager *fm = [NSFileManager defaultManager];
    NSArray *files = [fm contentsOfDirectoryAtPath:dir error:error];
    if (!files) return NO;
    for (NSString *n in files) {
        NSString *src = [dir stringByAppendingPathComponent:n];
        NSString *dst = [[self documentsPath] stringByAppendingPathComponent:n];
        if ([fm fileExistsAtPath:dst]) [fm removeItemAtPath:dst error:nil];
        if (![fm copyItemAtPath:src toPath:dst error:error]) return NO;
    }
    return YES;
}

+ (BOOL)setStat:(NSString *)stat value:(long long)value file:(NSString *)path error:(NSError **)error
{
    return [self setStats:@{ stat: @(value) } file:path error:error];
}

+ (BOOL)setStats:(NSDictionary<NSString *, NSNumber *> *)stats file:(NSString *)path error:(NSError **)error
{
    NSDictionary *json = [self loadJSON:path error:error];
    if (!json) return NO;

    BOOL any = NO;
    for (NSString *k in stats) {
        if (nms_set_stat_in_node(json, k, stats[k].longLongValue)) any = YES;
    }
    if (!any) {
        if (error) *error = nms_err(8, @"存档里没有匹配的统计项");
        return NO;
    }
    return [self writeJSON:json to:path error:error];
}

@end
