#import <UIKit/UIKit.h>

NS_ASSUME_NONNULL_BEGIN

/// 悬浮窗。调用 present 后常驻，点击悬浮球展开菜单，收起后继续游戏。
@interface NMSMenuWindow : UIWindow

+ (void)present;
+ (void)dismiss;
+ (BOOL)isPresented;

@end

NS_ASSUME_NONNULL_END
