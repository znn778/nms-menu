#import <UIKit/UIKit.h>
#import <objc/runtime.h>

#import "NMSMenuWindow.h"
#import "NMSPrefs.h"
#import "NMSHooks.h"

// ---------------------------------------------------------------------------
// 入口：不依赖 Logos / substrate，纯 runtime 实现，可用 clang 直编。
// ---------------------------------------------------------------------------

static IMP orig_didEnterBackground = NULL;
static IMP orig_willResignActive = NULL;

static void nms_didEnterBackground(id self, SEL _cmd)
{
    if ([NMSPrefs noPause]) return;
    if (orig_didEnterBackground) {
        ((void (*)(id, SEL))orig_didEnterBackground)(self, _cmd);
    }
}

static void nms_willResignActive(id self, SEL _cmd)
{
    if ([NMSPrefs noPause]) return;
    if (orig_willResignActive) {
        ((void (*)(id, SEL))orig_willResignActive)(self, _cmd);
    }
}

__attribute__((constructor))
static void nms_menu_init(void)
{
    @autoreleasepool {
        Class app = objc_getClass("UIApplication");

        SEL s1 = sel_registerName("_applicationDidEnterBackground");
        Method m1 = app ? class_getInstanceMethod(app, s1) : NULL;
        if (m1) {
            orig_didEnterBackground = method_setImplementation(m1, (IMP)nms_didEnterBackground);
        }

        SEL s2 = sel_registerName("_applicationWillResignActive");
        Method m2 = app ? class_getInstanceMethod(app, s2) : NULL;
        if (m2) {
            orig_willResignActive = method_setImplementation(m2, (IMP)nms_willResignActive);
        }

        // 恢复上次开启的代码补丁（补丁直接改主程序机器码，加载时就能打）
        [NMSHooks restoreAll];

        // 启动完成后延迟 2 秒挂悬浮窗，避开引擎初始化阶段
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
