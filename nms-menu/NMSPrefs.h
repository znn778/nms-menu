#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>

NS_ASSUME_NONNULL_BEGIN

@interface NMSPrefs : NSObject

+ (BOOL)noPause;
+ (void)setNoPause:(BOOL)v;

+ (BOOL)showFPS;
+ (void)setShowFPS:(BOOL)v;

+ (BOOL)freeze;
+ (void)setFreeze:(BOOL)v;

+ (CGPoint)ballCenter;
+ (void)setBallCenter:(CGPoint)p;

+ (BOOL)ballHidden;
+ (void)setBallHidden:(BOOL)v;

@end

NS_ASSUME_NONNULL_END
