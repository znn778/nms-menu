#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#import <substrate.h>

#import "NMSMenuWindow.h"
#import "NMSPrefs.h"

// ---------------------------------------------------------------------------
// 防暂停：UIApplication 的私有回调。用 MSHookMessageEx + 存在性检查，
// 方法不存在时直接跳过，不会因为 %orig 为空而崩。
// ---------------------------------------------------------------------------
static void (*orig_didEnterBackground)(id, SEL);
static void (*orig_willResignActive)(id, SEL);

static void nms_didEnterBackground(id self, SEL _cmd)
{
    if ([NMSPrefs noPause]) return;
    if (orig_didEnterBackground) orig_didEnterBackground(self, _cmd);
}

static void nms_willResignActive(id self, SEL _cmd)
{
    if ([NMSPrefs noPause]) return;
    if (orig_willResignActive) orig_willResignActive(self, _cmd);
}

%ctor {
    @autoreleasepool {
        Class app = objc_getClass("UIApplication");

        Method m1 = class_getInstanceMethod(app, @selector(_applicationDidEnterBackground));
        if (m1) {
            MSHookMessageEx(app, @selector(_applicationDidEnterBackground),
                            (IMP)nms_didEnterBackground, (IMP *)&orig_didEnterBackground);
        }

        Method m2 = class_getInstanceMethod(app, @selector(_applicationWillResignActive));
        if (m2) {
            MSHookMessageEx(app, @selector(_applicationWillResignActive),
                            (IMP)nms_willResignActive, (IMP *)&orig_willResignActive);
        }

        // 游戏启动完成后延迟 2 秒挂上悬浮窗，避开启动阶段的 UI 构建
        [[NSNotificationCenter defaultCenter]
            addObserverForName:UIApplicationDidFinishLaunchingNotification
                        object:nil
                         queue:[NSOperationQueue mainQueue]
                    usingBlock:^(NSNotification *note) {
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(2.0 * NSEC_PER_SEC)),
                           dispatch_get_main_queue(), ^{
                [NMSMenuWindow present];
            });
        }];
    }
}
