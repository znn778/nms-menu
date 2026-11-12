// empty.m - 空壳 dylib 源码
//
// 用途：把 iOSGods 那两个「硬链接」库换成惰性空壳。
// 主二进制对 libnomanssky / iGameGod 的未定义符号引用数为 0，
// 所以一个不导出任何符号的 dylib 就能满足 dyld 的依赖检查，
// 同时不执行任何代码 —— 菜单不出现、验证弹窗不出现。
//
// 这样主二进制可以保持逐字节不变，签名骨架也原样保留。

__attribute__((used)) static const char kNMSEmptyStub[] = "NMSMenu empty stub";
