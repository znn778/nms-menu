#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

@interface NMSSaveTool : NSObject

/// 游戏存档目录（app 容器 Documents）
+ (NSString *)documentsPath;
/// 目录下所有 .hg 存档绝对路径
+ (NSArray<NSString *> *)saveFiles;

/// 解析存档摘要：version / playerName / units / nanites / statCount
+ (nullable NSDictionary *)infoForFile:(NSString *)path;

/// 把所有 .hg 备份到 Documents/NMSMenuBackups/<时间戳>/
+ (BOOL)backupAllWithError:(NSError **)error;
/// 最近一次备份目录
+ (nullable NSString *)latestBackupDir;
/// 从最近一次备份还原
+ (BOOL)restoreLatestWithError:(NSError **)error;

/// 改单个统计项（如 UNITS / NANITES）
+ (BOOL)setStat:(NSString *)stat value:(long long)value file:(NSString *)path error:(NSError **)error;
/// 批量改
+ (BOOL)setStats:(NSDictionary<NSString *, NSNumber *> *)stats file:(NSString *)path error:(NSError **)error;

@end

NS_ASSUME_NONNULL_END
