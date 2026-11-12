#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

/// 运行时二进制补丁：直接改主程序机器码，不 hook、不注入 trampoline。
/// 每个补丁带原始字节校验，版本不匹配直接拒绝，不会把游戏改崩。
@interface NMSHooks : NSObject

/// 所有可用补丁：key / title / desc / enabled
+ (NSArray<NSDictionary *> *)allPatches;

/// 开关某个补丁
+ (BOOL)setPatch:(NSString *)key enabled:(BOOL)enabled;

/// 启动时恢复用户上次的选择
+ (void)restoreAll;

/// 主程序基址（供调试显示）
+ (uint64_t)mainBase;

@end

NS_ASSUME_NONNULL_END
