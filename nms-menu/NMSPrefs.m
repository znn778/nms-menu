#import "NMSPrefs.h"

static NSString *const kPrefix = @"com.seagull.nmsmenu.";

@implementation NMSPrefs

+ (NSUserDefaults *)d { return [NSUserDefaults standardUserDefaults]; }

+ (BOOL)noPause { return [[self d] boolForKey:[kPrefix stringByAppendingString:@"noPause"]]; }
+ (void)setNoPause:(BOOL)v { [[self d] setBool:v forKey:[kPrefix stringByAppendingString:@"noPause"]]; }

+ (BOOL)showFPS { return [[self d] boolForKey:[kPrefix stringByAppendingString:@"showFPS"]]; }
+ (void)setShowFPS:(BOOL)v { [[self d] setBool:v forKey:[kPrefix stringByAppendingString:@"showFPS"]]; }

+ (BOOL)freeze { return [[self d] boolForKey:[kPrefix stringByAppendingString:@"freeze"]]; }
+ (void)setFreeze:(BOOL)v { [[self d] setBool:v forKey:[kPrefix stringByAppendingString:@"freeze"]]; }

+ (CGPoint)ballCenter
{
    NSArray *a = [[self d] arrayForKey:[kPrefix stringByAppendingString:@"ballCenter"]];
    if (a.count == 2) return CGPointMake([a[0] doubleValue], [a[1] doubleValue]);
    return CGPointMake(-1, -1); // 未初始化
}

+ (void)setBallCenter:(CGPoint)p
{
    [[self d] setObject:@[@(p.x), @(p.y)] forKey:[kPrefix stringByAppendingString:@"ballCenter"]];
}

+ (BOOL)ballHidden { return [[self d] boolForKey:[kPrefix stringByAppendingString:@"ballHidden"]]; }
+ (void)setBallHidden:(BOOL)v { [[self d] setBool:v forKey:[kPrefix stringByAppendingString:@"ballHidden"]]; }

@end
