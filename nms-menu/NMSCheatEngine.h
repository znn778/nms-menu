#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

typedef NS_ENUM(NSInteger, NMSFilterMode) {
    NMSFilterChanged = 0,
    NMSFilterUnchanged,
    NMSFilterIncreased,
    NMSFilterDecreased,
};

@interface NMSCheatEngine : NSObject

+ (instancetype)shared;

@property (nonatomic, readonly) NSUInteger resultCount;
@property (nonatomic, readonly) NSUInteger scannedRegions;
@property (nonatomic, readonly) uint64_t scannedBytes;

/// 首次扫描 int32
- (NSUInteger)firstScan:(int32_t)value;
/// 在结果中按精确值过滤
- (NSUInteger)filterExact:(int32_t)value;
/// 在结果中按变化趋势过滤
- (NSUInteger)filterMode:(NMSFilterMode)mode;
/// 取前 N 个候选
- (NSArray<NSDictionary *> *)topResults:(NSUInteger)limit;
/// 把所有候选写成同一个值
- (NSUInteger)writeAll:(int32_t)value;
/// 写单个地址
- (BOOL)writeAt:(uint64_t)addr value:(int32_t)value;
/// 锁定：冻结当前候选值，每 100ms 回写一次
- (void)setFreeze:(BOOL)freeze value:(int32_t)value;
@property (nonatomic, readonly) BOOL frozen;

- (void)clear;

@end

NS_ASSUME_NONNULL_END
