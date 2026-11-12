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

// ---------------------------------------------------------------------------
// 构造函数必须做到「绝不抛、绝不阻塞、绝不碰游戏状态」。
// 任何一步失败都只是菜单不出现，不能让 dyld 把进程带走。
// ---------------------------------------------------------------------------

// 紧急开关：往 App 的 NSUserDefaults 里写 nmsmenu.disable = 1 即可彻底停用本插件
static BOOL nms_disabled(void)
{
    @try {
        id v = [[NSUserDefaults standardUserDefaults] objectForKey:@"nmsmenu.disable"];
        return v ? [v boolValue] : NO;
    } @catch (__unused NSException *e) {
        return NO;
    }
}

static void nms_install_hooks(void)
{
    @try {
        Class app = objc_getClass("UIApplication");
        if (!app) return;

        SEL s1 = sel_registerName("_applicationDidEnterBackground");
        Method m1 = class_getInstanceMethod(app, s1);
        if (m1) {
            orig_didEnterBackground = method_setImplementation(m1, (IMP)nms_didEnterBackground);
        }

        SEL s2 = sel_registerName("_applicationWillResignActive");
        Method m2 = class_getInstanceMethod(app, s2);
        if (m2) {
            orig_willResignActive = method_setImplementation(m2, (IMP)nms_willResignActive);
        }
    } @catch (__unused NSException *e) {
        NSLog(@"[NMSMenu] install_hooks 异常: %@", e);
    }
}

static void nms_after_launch(void)
{
    @try {
        // 恢复上次开启的代码补丁。放到启动完成后做，避免在 dyld 初始化阶段
        // 去 vm_protect 主程序 __TEXT（那是最容易被系统判死的一步）。
        [NMSHooks restoreAll];
    } @catch (__unused NSException *e) {
        NSLog(@"[NMSMenu] restoreAll 异常: %@", e);
    }

    @try {
        [NMSMenuWindow present];
    } @catch (__unused NSException *e) {
        NSLog(@"[NMSMenu] present 异常: %@", e);
    }
}

__attribute__((constructor))
static void nms_menu_init(void)
{
    if (nms_disabled()) {
        NSLog(@"[NMSMenu] 已被 nmsmenu.disable 停用");
        return;
    }

    @autoreleasepool {
        nms_install_hooks();

        // 启动完成后延迟 3 秒挂悬浮窗，避开引擎初始化阶段
        [[NSNotificationCenter defaultCenter]
            addObserverForName:UIApplicationDidFinishLaunchingNotification
                        object:nil
                         queue:[NSOperationQueue mainQueue]
                    usingBlock:^(NSNotification *note) {
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(3.0 * NSEC_PER_SEC)),
                           dispatch_get_main_queue(), ^{
                if (nms_disabled()) return;
                nms_after_launch();
            });
        }];
    }
}
