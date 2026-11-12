#import "NMSMenuWindow.h"
#import "NMSCheatEngine.h"
#import "NMSSaveTool.h"
#import "NMSPrefs.h"
#import <QuartzCore/QuartzCore.h>
#import <mach/mach.h>
#import <stdlib.h>

#define kPanelW   304.0
#define kPanelH   470.0
#define kBallSize 54.0

#pragma mark - 穿透视图（空白处不拦截游戏触摸）

@interface NMSPassView : UIView
@end

@implementation NMSPassView
- (UIView *)hitTest:(CGPoint)point withEvent:(UIEvent *)event
{
    UIView *v = [super hitTest:point withEvent:event];
    return (v == self) ? nil : v;
}
@end

#pragma mark - 根控制器

@interface NMSMenuRootController : UIViewController

@property (nonatomic, strong) UIButton *ball;
@property (nonatomic, strong) UIView *panel;
@property (nonatomic, strong) UILabel *fpsLabel;
@property (nonatomic, strong) CADisplayLink *link;

@property (nonatomic, strong) UITextField *valueField;
@property (nonatomic, strong) UILabel *resultLabel;
@property (nonatomic, strong) UILabel *saveInfoLabel;
@property (nonatomic, strong) UILabel *statLabel;
@property (nonatomic, strong) UISwitch *freezeSwitch;

@property (nonatomic, assign) NSInteger frames;
@property (nonatomic, assign) CFTimeInterval lastTick;

@end

@implementation NMSMenuRootController

- (void)loadView
{
    self.view = [[NMSPassView alloc] initWithFrame:UIScreen.mainScreen.bounds];
}

- (void)viewDidLayoutSubviews
{
    [super viewDidLayoutSubviews];
    if (self.ball) self.ball.center = [self clampBall:self.ball.center];
    if (self.panel && !self.panel.hidden) [self layoutPanel];
}

- (void)viewDidLoad
{
    [super viewDidLoad];
    self.view.backgroundColor = [UIColor clearColor];

    [self buildBall];
    [self buildPanel];
    [self buildFPS];
    [self refreshSaveInfo];
    [self refreshStat];

    [[NSNotificationCenter defaultCenter] addObserver:self
                                             selector:@selector(onOrientation)
                                                 name:UIDeviceOrientationDidChangeNotification
                                               object:nil];
}

- (void)dealloc
{
    [_link invalidate];
    [[NSNotificationCenter defaultCenter] removeObserver:self];
}

#pragma mark 悬浮球

- (void)buildBall
{
    UIButton *b = [UIButton buttonWithType:UIButtonTypeCustom];
    b.frame = CGRectMake(0, 0, kBallSize, kBallSize);
    b.backgroundColor = [UIColor colorWithWhite:0.08 alpha:0.86];
    b.layer.cornerRadius = kBallSize / 2;
    b.layer.borderWidth = 1.5;
    b.layer.borderColor = [UIColor colorWithRed:0.30 green:0.85 blue:0.75 alpha:0.95].CGColor;
    b.layer.shadowColor = [UIColor blackColor].CGColor;
    b.layer.shadowOpacity = 0.45;
    b.layer.shadowRadius = 6;
    b.layer.shadowOffset = CGSizeMake(0, 2);
    [b setTitle:@"NMS" forState:UIControlStateNormal];
    b.titleLabel.font = [UIFont boldSystemFontOfSize:13];
    [b setTitleColor:[UIColor colorWithRed:0.30 green:0.85 blue:0.75 alpha:1] forState:UIControlStateNormal];
    [b addTarget:self action:@selector(togglePanel) forControlEvents:UIControlEventTouchUpInside];
    [b addGestureRecognizer:[[UIPanGestureRecognizer alloc] initWithTarget:self action:@selector(dragBall:)]];
    [self.view addSubview:b];
    self.ball = b;
    [self restoreBallPosition];
}

- (void)restoreBallPosition
{
    CGPoint p = [NMSPrefs ballCenter];
    CGSize s = self.view.bounds.size;
    if (p.x < 0 || p.y < 0) p = CGPointMake(s.width - 46, s.height * 0.32);
    self.ball.center = [self clampBall:p];
}

- (CGPoint)clampBall:(CGPoint)p
{
    CGSize s = self.view.bounds.size;
    CGFloat half = kBallSize / 2;
    p.x = MAX(half + 4, MIN(s.width - half - 4, p.x));
    p.y = MAX(half + 30, MIN(s.height - half - 20, p.y));
    return p;
}

- (void)dragBall:(UIPanGestureRecognizer *)g
{
    CGPoint t = [g translationInView:self.view];
    CGPoint c = CGPointMake(self.ball.center.x + t.x, self.ball.center.y + t.y);
    self.ball.center = [self clampBall:c];
    [g setTranslation:CGPointZero inView:self.view];

    if (g.state == UIGestureRecognizerStateEnded ||
        g.state == UIGestureRecognizerStateCancelled) {
        CGSize s = self.view.bounds.size;
        CGFloat x = (self.ball.center.x < s.width / 2) ? kBallSize / 2 + 6 : s.width - kBallSize / 2 - 6;
        [UIView animateWithDuration:0.22 animations:^{
            self.ball.center = CGPointMake(x, self.ball.center.y);
        }];
        [NMSPrefs setBallCenter:self.ball.center];
    }
}

- (void)onOrientation
{
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.2 * NSEC_PER_SEC)),
                   dispatch_get_main_queue(), ^{
        self.ball.center = [self clampBall:self.ball.center];
        if (self.panel && !self.panel.hidden) [self layoutPanel];
    });
}

#pragma mark 面板

- (UILabel *)headerLabel:(NSString *)text
{
    UILabel *l = [UILabel new];
    l.text = text;
    l.font = [UIFont boldSystemFontOfSize:12];
    l.textColor = [UIColor colorWithRed:0.30 green:0.85 blue:0.75 alpha:1];
    return l;
}

- (UIButton *)makeButton:(NSString *)title action:(SEL)sel
{
    UIButton *b = [UIButton buttonWithType:UIButtonTypeSystem];
    [b setTitle:title forState:UIControlStateNormal];
    [b setTitleColor:[UIColor whiteColor] forState:UIControlStateNormal];
    b.titleLabel.font = [UIFont systemFontOfSize:12 weight:UIFontWeightMedium];
    b.backgroundColor = [UIColor colorWithWhite:1 alpha:0.13];
    b.layer.cornerRadius = 7;
    [b.heightAnchor constraintEqualToConstant:32].active = YES;
    [b addTarget:self action:sel forControlEvents:UIControlEventTouchUpInside];
    return b;
}

- (UIStackView *)row:(NSArray<UIView *> *)views
{
    UIStackView *s = [[UIStackView alloc] initWithArrangedSubviews:views];
    s.axis = UILayoutConstraintAxisHorizontal;
    s.distribution = UIStackViewDistributionFillEqually;
    s.spacing = 6;
    return s;
}

- (UIView *)switchRow:(NSString *)title on:(BOOL)on action:(SEL)sel
{
    UIView *c = [UIView new];
    UILabel *l = [UILabel new];
    l.text = title;
    l.font = [UIFont systemFontOfSize:12.5];
    l.textColor = [UIColor colorWithWhite:0.95 alpha:1];
    l.translatesAutoresizingMaskIntoConstraints = NO;
    UISwitch *sw = [UISwitch new];
    sw.on = on;
    sw.transform = CGAffineTransformMakeScale(0.72, 0.72);
    sw.translatesAutoresizingMaskIntoConstraints = NO;
    [sw addTarget:self action:sel forControlEvents:UIControlEventValueChanged];
    [c addSubview:l];
    [c addSubview:sw];
    [NSLayoutConstraint activateConstraints:@[
        [l.leadingAnchor constraintEqualToAnchor:c.leadingAnchor constant:2],
        [l.centerYAnchor constraintEqualToAnchor:c.centerYAnchor],
        [sw.trailingAnchor constraintEqualToAnchor:c.trailingAnchor constant:2],
        [sw.centerYAnchor constraintEqualToAnchor:c.centerYAnchor],
        [c.heightAnchor constraintEqualToConstant:34],
    ]];
    return c;
}

- (void)buildPanel
{
    CGFloat w = kPanelW, h = kPanelH;
    UIView *p = [[UIView alloc] initWithFrame:CGRectMake(0, 0, w, h)];
    p.backgroundColor = [UIColor clearColor];
    p.layer.cornerRadius = 16;
    p.layer.masksToBounds = YES;
    p.hidden = YES;

    UIVisualEffectView *blur = [[UIVisualEffectView alloc] initWithEffect:
                                [UIBlurEffect effectWithStyle:UIBlurEffectStyleDark]];
    blur.frame = p.bounds;
    blur.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    [p addSubview:blur];

    // 顶部标题栏
    UIView *bar = [[UIView alloc] initWithFrame:CGRectMake(0, 0, w, 38)];
    bar.autoresizingMask = UIViewAutoresizingFlexibleWidth;
    UILabel *title = [UILabel new];
    title.text = @"NMS MENU";
    title.font = [UIFont boldSystemFontOfSize:13];
    title.textColor = [UIColor colorWithRed:0.30 green:0.85 blue:0.75 alpha:1];
    title.frame = CGRectMake(14, 0, 180, 38);
    [bar addSubview:title];

    UIButton *min = [UIButton buttonWithType:UIButtonTypeSystem];
    [min setTitle:@"—" forState:UIControlStateNormal];
    min.titleLabel.font = [UIFont boldSystemFontOfSize:18];
    [min setTitleColor:[UIColor colorWithWhite:0.9 alpha:1] forState:UIControlStateNormal];
    min.frame = CGRectMake(w - 44, 2, 38, 34);
    [min addTarget:self action:@selector(togglePanel) forControlEvents:UIControlEventTouchUpInside];
    [bar addSubview:min];
    [p addSubview:bar];

    // 滚动内容
    UIScrollView *sv = [[UIScrollView alloc] initWithFrame:CGRectMake(0, 38, w, h - 38)];
    sv.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    sv.showsVerticalScrollIndicator = NO;
    [p addSubview:sv];

    UIStackView *stack = [[UIStackView alloc] init];
    stack.axis = UILayoutConstraintAxisVertical;
    stack.spacing = 7;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [sv addSubview:stack];
    [NSLayoutConstraint activateConstraints:@[
        [stack.topAnchor constraintEqualToAnchor:sv.contentLayoutGuide.topAnchor constant:6],
        [stack.bottomAnchor constraintEqualToAnchor:sv.contentLayoutGuide.bottomAnchor constant:-12],
        [stack.leadingAnchor constraintEqualToAnchor:sv.frameLayoutGuide.leadingAnchor constant:12],
        [stack.trailingAnchor constraintEqualToAnchor:sv.frameLayoutGuide.trailingAnchor constant:-12],
    ]];

    // ---- 数值 ----
    [stack addArrangedSubview:[self headerLabel:@"数值修改"]];

    self.valueField = [UITextField new];
    self.valueField.placeholder = @"输入当前数值，如 12345";
    self.valueField.keyboardType = UIKeyboardTypeNumberPad;
    self.valueField.font = [UIFont systemFontOfSize:13];
    self.valueField.textColor = [UIColor whiteColor];
    self.valueField.backgroundColor = [UIColor colorWithWhite:1 alpha:0.10];
    self.valueField.layer.cornerRadius = 7;
    self.valueField.leftView = [[UIView alloc] initWithFrame:CGRectMake(0, 0, 8, 30)];
    self.valueField.leftViewMode = UITextFieldViewModeAlways;
    [self.valueField.heightAnchor constraintEqualToConstant:32].active = YES;
    [stack addArrangedSubview:self.valueField];

    [stack addArrangedSubview:[self row:@[
        [self makeButton:@"首次扫描" action:@selector(doScan)],
        [self makeButton:@"精确过滤" action:@selector(doFilterExact)],
        [self makeButton:@"清空" action:@selector(doClear)],
    ]]];
    [stack addArrangedSubview:[self row:@[
        [self makeButton:@"变大了" action:@selector(doFilterInc)],
        [self makeButton:@"变小了" action:@selector(doFilterDec)],
        [self makeButton:@"没变" action:@selector(doFilterSame)],
    ]]];
    [stack addArrangedSubview:[self row:@[
        [self makeButton:@"写入全部" action:@selector(doWrite)],
        [self makeButton:@"打印地址" action:@selector(doPrint)],
    ]]];

    self.resultLabel = [UILabel new];
    self.resultLabel.font = [UIFont monospacedSystemFontOfSize:11 weight:UIFontWeightRegular];
    self.resultLabel.textColor = [UIColor colorWithWhite:0.75 alpha:1];
    self.resultLabel.numberOfLines = 0;
    self.resultLabel.text = @"候选: 0";
    [stack addArrangedSubview:self.resultLabel];

    // ---- 存档 ----
    [stack addArrangedSubview:[self headerLabel:@"存档"]];
    self.saveInfoLabel = [UILabel new];
    self.saveInfoLabel.font = [UIFont monospacedSystemFontOfSize:10.5 weight:UIFontWeightRegular];
    self.saveInfoLabel.textColor = [UIColor colorWithWhite:0.8 alpha:1];
    self.saveInfoLabel.numberOfLines = 0;
    [stack addArrangedSubview:self.saveInfoLabel];

    [stack addArrangedSubview:[self row:@[
        [self makeButton:@"刷新" action:@selector(refreshSaveInfo)],
        [self makeButton:@"备份" action:@selector(doBackup)],
        [self makeButton:@"还原" action:@selector(doRestore)],
    ]]];
    [stack addArrangedSubview:[self row:@[
        [self makeButton:@"UNITS 改满" action:@selector(doMaxUnits)],
        [self makeButton:@"NANITES 改满" action:@selector(doMaxNanites)],
    ]]];

    // ---- 开关 ----
    [stack addArrangedSubview:[self headerLabel:@"开关"]];
    [stack addArrangedSubview:[self switchRow:@"后台不暂停"
                                          on:[NMSPrefs noPause]
                                      action:@selector(onNoPause:)]];
    [stack addArrangedSubview:[self switchRow:@"显示 FPS"
                                          on:[NMSPrefs showFPS]
                                      action:@selector(onShowFPS:)]];
    self.freezeSwitch = [UISwitch new];
    {
        UIView *c = [self switchRow:@"锁定数值（每 100ms 回写）"
                                 on:[[NMSCheatEngine shared] frozen]
                             action:@selector(onFreeze:)];
        for (UIView *v in c.subviews) {
            if ([v isKindOfClass:[UISwitch class]]) self.freezeSwitch = (UISwitch *)v;
        }
        [stack addArrangedSubview:c];
    }

    // ---- 信息 ----
    [stack addArrangedSubview:[self headerLabel:@"信息"]];
    self.statLabel = [UILabel new];
    self.statLabel.font = [UIFont monospacedSystemFontOfSize:10.5 weight:UIFontWeightRegular];
    self.statLabel.textColor = [UIColor colorWithWhite:0.7 alpha:1];
    self.statLabel.numberOfLines = 0;
    [stack addArrangedSubview:self.statLabel];

    [self.view addSubview:p];
    self.panel = p;
    [self layoutPanel];
}

- (void)layoutPanel
{
    CGSize s = self.view.bounds.size;
    CGFloat w = kPanelW, h = MIN(kPanelH, s.height - 80);
    CGRect f = self.panel.frame;
    f.size = CGSizeMake(w, h);

    CGPoint c = self.ball.center;
    CGFloat x = c.x + (c.x > s.width / 2 ? -(w / 2 + 34) : (w / 2 + 34));
    x = MAX(8, MIN(s.width - w - 8, x - w / 2));
    CGFloat y = MAX(40, MIN(s.height - h - 20, c.y - h / 2));
    f.origin = CGPointMake(x, y);
    self.panel.frame = f;
}

#pragma mark FPS

- (void)buildFPS
{
    UILabel *l = [UILabel new];
    l.font = [UIFont monospacedSystemFontOfSize:11 weight:UIFontWeightBold];
    l.textColor = [UIColor colorWithRed:0.30 green:0.95 blue:0.75 alpha:1];
    l.backgroundColor = [UIColor colorWithWhite:0 alpha:0.45];
    l.textAlignment = NSTextAlignmentCenter;
    l.layer.cornerRadius = 4;
    l.layer.masksToBounds = YES;
    l.frame = CGRectMake(8, 8, 62, 18);
    l.hidden = ![NMSPrefs showFPS];
    [self.view addSubview:l];
    self.fpsLabel = l;

    CADisplayLink *link = [CADisplayLink displayLinkWithTarget:self selector:@selector(tick:)];
    [link addToRunLoop:[NSRunLoop mainRunLoop] forMode:NSRunLoopCommonModes];
    self.link = link;
    self.lastTick = CACurrentMediaTime();
}

- (void)tick:(CADisplayLink *)link
{
    self.frames++;
    CFTimeInterval now = CACurrentMediaTime();
    if (now - self.lastTick >= 1.0) {
        self.fpsLabel.text = [NSString stringWithFormat:@"%ld FPS", (long)self.frames];
        self.frames = 0;
        self.lastTick = now;
        [self refreshStat];
    }
}

#pragma mark 交互

- (void)togglePanel
{
    BOOL show = self.panel.hidden;
    if (show) {
        [self layoutPanel];
        self.panel.hidden = NO;
        self.panel.alpha = 0;
        self.panel.transform = CGAffineTransformMakeScale(0.9, 0.9);
        [UIView animateWithDuration:0.18 animations:^{
            self.panel.alpha = 1;
            self.panel.transform = CGAffineTransformIdentity;
        }];
        [self refreshSaveInfo];
        [self refreshStat];
    } else {
        [UIView animateWithDuration:0.15 animations:^{
            self.panel.alpha = 0;
            self.panel.transform = CGAffineTransformMakeScale(0.9, 0.9);
        } completion:^(BOOL f) {
            self.panel.hidden = YES;
            self.panel.alpha = 1;
            self.panel.transform = CGAffineTransformIdentity;
        }];
    }
}

- (int32_t)inputValue
{
    return (int32_t)strtoll(self.valueField.text.UTF8String, NULL, 10);
}

- (void)flash:(NSString *)msg
{
    self.resultLabel.text = msg;
}

#pragma mark 数值动作

- (void)doScan
{
    int32_t v = [self inputValue];
    [self flash:@"扫描中..."];
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        NSUInteger n = [[NMSCheatEngine shared] firstScan:v];
        dispatch_async(dispatch_get_main_queue(), ^{
            [self flash:[NSString stringWithFormat:@"候选: %lu  (扫描 %.0f MB)",
                         (unsigned long)n,
                         [[NMSCheatEngine shared] scannedBytes] / 1048576.0]];
            [self refreshStat];
        });
    });
}

- (void)doFilterExact
{
    NSUInteger n = [[NMSCheatEngine shared] filterExact:[self inputValue]];
    [self flash:[NSString stringWithFormat:@"精确过滤后候选: %lu", (unsigned long)n]];
}

- (void)doFilterInc
{
    NSUInteger n = [[NMSCheatEngine shared] filterMode:NMSFilterIncreased];
    [self flash:[NSString stringWithFormat:@"变大过滤后候选: %lu", (unsigned long)n]];
}

- (void)doFilterDec
{
    NSUInteger n = [[NMSCheatEngine shared] filterMode:NMSFilterDecreased];
    [self flash:[NSString stringWithFormat:@"变小过滤后候选: %lu", (unsigned long)n]];
}

- (void)doFilterSame
{
    NSUInteger n = [[NMSCheatEngine shared] filterMode:NMSFilterUnchanged];
    [self flash:[NSString stringWithFormat:@"未变过滤后候选: %lu", (unsigned long)n]];
}

- (void)doClear
{
    [[NMSCheatEngine shared] clear];
    [self flash:@"候选: 0"];
}

- (void)doWrite
{
    int32_t v = [self inputValue];
    NSUInteger n = [[NMSCheatEngine shared] writeAll:v];
    if (self.freezeSwitch.isOn) {
        [[NMSCheatEngine shared] setFreeze:YES value:v];
    }
    [self flash:[NSString stringWithFormat:@"已写入 %lu 处 = %d", (unsigned long)n, v]];
}

- (void)doPrint
{
    NSArray *top = [[NMSCheatEngine shared] topResults:12];
    NSMutableString *s = [NSMutableString stringWithFormat:@"候选: %lu\n",
                          (unsigned long)[[NMSCheatEngine shared] resultCount]];
    for (NSDictionary *d in top) {
        [s appendFormat:@"0x%llx = %@\n",
         [d[@"addr"] unsignedLongLongValue], d[@"value"]];
    }
    [self flash:s];
}

#pragma mark 存档动作

- (void)refreshSaveInfo
{
    NSArray *files = [NMSSaveTool saveFiles];
    if (files.count == 0) {
        self.saveInfoLabel.text = @"未找到 .hg 存档";
        return;
    }
    NSMutableString *s = [NSMutableString string];
    for (NSString *f in files) {
        NSDictionary *i = [NMSSaveTool infoForFile:f];
        if (i[@"error"]) {
            [s appendFormat:@"%@: %@\n", i[@"file"], i[@"error"]];
            continue;
        }
        [s appendFormat:@"%@  v%@  %@\n  UNITS=%@  NANITES=%@\n",
         i[@"file"], i[@"version"], i[@"player"], i[@"units"], i[@"nanites"]];
    }
    self.saveInfoLabel.text = s;
}

- (void)alert:(NSString *)title msg:(NSString *)msg
{
    UIAlertController *a = [UIAlertController alertControllerWithTitle:title
                                                              message:msg
                                                       preferredStyle:UIAlertControllerStyleAlert];
    [a addAction:[UIAlertAction actionWithTitle:@"好" style:UIAlertActionStyleDefault handler:nil]];
    [self presentViewController:a animated:YES completion:nil];
}

- (void)doBackup
{
    NSError *e = nil;
    BOOL ok = [NMSSaveTool backupAllWithError:&e];
    [self alert:ok ? @"备份成功" : @"备份失败" msg:ok ? [NMSSaveTool latestBackupDir] : e.localizedDescription];
    [self refreshSaveInfo];
}

- (void)doRestore
{
    NSError *e = nil;
    BOOL ok = [NMSSaveTool restoreLatestWithError:&e];
    [self alert:ok ? @"还原成功" : @"还原失败" msg:ok ? @"已从最近备份恢复，请重启游戏" : e.localizedDescription];
    [self refreshSaveInfo];
}

- (void)applyStats:(NSDictionary *)stats
{
    NSArray *files = [NMSSaveTool saveFiles];
    if (files.count == 0) { [self alert:@"失败" msg:@"没有找到存档"]; return; }
    NSMutableString *log = [NSMutableString string];
    for (NSString *f in files) {
        NSError *e = nil;
        BOOL ok = [NMSSaveTool setStats:stats file:f error:&e];
        [log appendFormat:@"%@: %@\n", f.lastPathComponent, ok ? @"OK" : e.localizedDescription];
    }
    [self alert:@"写入结果" msg:log];
    [self refreshSaveInfo];
}

- (void)doMaxUnits
{
    // 20 亿：够用且不会触发 int32 溢出成负数
    [self applyStats:@{ @"UNITS": @(2000000000LL) }];
}

- (void)doMaxNanites
{
    [self applyStats:@{ @"NANITES": @(100000000LL) }];
}

#pragma mark 开关动作

- (void)onNoPause:(UISwitch *)sw { [NMSPrefs setNoPause:sw.isOn]; }

- (void)onShowFPS:(UISwitch *)sw
{
    [NMSPrefs setShowFPS:sw.isOn];
    self.fpsLabel.hidden = !sw.isOn;
}

- (void)onFreeze:(UISwitch *)sw
{
    [[NMSCheatEngine shared] setFreeze:sw.isOn value:[self inputValue]];
    [NMSPrefs setFreeze:sw.isOn];
    [self flash:sw.isOn ? @"已锁定当前候选值" : @"已解除锁定"];
}

- (void)refreshStat
{
    struct task_vm_info info;
    mach_msg_type_number_t count = TASK_VM_INFO_COUNT;
    double mb = 0;
    if (task_info(mach_task_self(), TASK_VM_INFO, (task_info_t)&info, &count) == KERN_SUCCESS) {
        mb = info.phys_footprint / 1048576.0;
    }
    self.statLabel.text = [NSString stringWithFormat:
        @"进程内存 %.0f MB\n候选地址 %lu\n扫描段 %lu",
        mb,
        (unsigned long)[[NMSCheatEngine shared] resultCount],
        (unsigned long)[[NMSCheatEngine shared] scannedRegions]];
}

@end

#pragma mark - 窗口

@implementation NMSMenuWindow

static NMSMenuWindow *_instance;

+ (BOOL)isPresented { return _instance != nil; }

+ (void)present
{
    if (_instance) return;
    if (![NSThread isMainThread]) {
        dispatch_async(dispatch_get_main_queue(), ^{ [self present]; });
        return;
    }

    UIWindowScene *scene = nil;
    for (UIScene *s in UIApplication.sharedApplication.connectedScenes) {
        if ([s isKindOfClass:[UIWindowScene class]] &&
            s.activationState == UISceneActivationStateForegroundActive) {
            scene = (UIWindowScene *)s;
            break;
        }
    }

    NMSMenuWindow *w = scene ? [[NMSMenuWindow alloc] initWithWindowScene:scene]
                             : [[NMSMenuWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    w.windowLevel = UIWindowLevelAlert + 1200;
    w.backgroundColor = [UIColor clearColor];
    w.rootViewController = [NMSMenuRootController new];
    w.hidden = NO;
    _instance = w;
}

+ (void)dismiss
{
    _instance.hidden = YES;
    _instance = nil;
}

@end
