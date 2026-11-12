#!/usr/bin/env python3
"""nms_cheat.py - 无人深空 iOS 内存扫描/修改器（Cheat Engine 式命令行）

依赖:
    pip install frida
    设备侧: 越狱 + frida-server 运行中（或用 TrollStore 版 frida）
    USB 连接后: frida-ps -U 应能看到 "No Man's Sky"

用法:
    python nms_cheat.py                  # 进入交互模式
    python nms_cheat.py --pid 1234       # 指定 pid
    python nms_cheat.py --host 192.168.1.10:27042

交互命令:
    modules                     列出模块与基址
    ranges [rw-]                列出可读写内存段
    scan <int>                  首次扫描 int32
    scanf <int>                 在结果里继续扫描（精确值）
    changed | unchanged         在结果里按"变/没变"过滤
    inc | dec                   在结果里按"变大/变小"过滤
    list [n]                    显示当前候选地址
    write <value>               把所有候选地址写成 value
    writeat <addr> <value>      写单个地址
    read <addr> [i32|i64|f32|f64|str]
    aob <pattern>               特征码扫描，如 "48 8B 05 ?? ?? ?? ??"
    stats                       当前候选数量
    q                           退出
"""
import argparse
import sys
import time

JS = r"""
const results = [];
let last = [];

rpc.exports = {
  init() {
    return Process.enumerateModules().map(m => ({name: m.name, base: m.base.toString(), size: m.size}));
  },
  ranges(prot) {
    return Process.enumerateRanges(prot || 'rw-').map(r => ({base: r.base.toString(), size: r.size, prot: r.protection}));
  },
  scan(value) {
    results.length = 0;
    const v = value | 0;
    for (const r of Process.enumerateRanges('rw-')) {
      if (r.size > 256 * 1024 * 1024) continue;
      try {
        const bytes = r.base.readByteArray(Math.min(r.size, 256 * 1024 * 1024));
        if (!bytes) continue;
        const u8 = new Uint8Array(bytes);
        for (let i = 0; i + 4 <= u8.length; i += 4) {
          const x = (u8[i] | (u8[i+1] << 8) | (u8[i+2] << 16) | (u8[i+3] << 24));
          if (x === v) results.push(r.base.add(i));
        }
      } catch (e) {}
    }
    last = results.map(p => { try { return p.readS32(); } catch (e) { return null; } });
    return results.length;
  },
  filter_exact(value) {
    const v = value | 0;
    for (let i = results.length - 1; i >= 0; i--) {
      let cur = null;
      try { cur = results[i].readS32(); } catch (e) {}
      if (cur !== v) results.splice(i, 1);
    }
    return results.length;
  },
  filter_mode(mode) {
    for (let i = results.length - 1; i >= 0; i--) {
      let cur = null;
      try { cur = results[i].readS32(); } catch (e) {}
      const old = last[i];
      let keep = false;
      if (mode === 'changed') keep = (cur !== old);
      else if (mode === 'unchanged') keep = (cur === old);
      else if (mode === 'inc') keep = (old !== null && cur !== null && cur > old);
      else if (mode === 'dec') keep = (old !== null && cur !== null && cur < old);
      if (!keep) results.splice(i, 1);
    }
    last = results.map(p => { try { return p.readS32(); } catch (e) { return null; } });
    return results.length;
  },
  list(n) {
    return results.slice(0, n || 40).map(p => {
      let v = null; try { v = p.readS32(); } catch (e) {}
      return {addr: p.toString(), value: v};
    });
  },
  write(value) {
    const v = value | 0;
    let n = 0;
    for (const p of results) { try { p.writeS32(v); n++; } catch (e) {} }
    return n;
  },
  write_at(addr, value) {
    const p = ptr(addr);
    p.writeS32(value | 0);
    return p.readS32();
  },
  read_at(addr, type) {
    const p = ptr(addr);
    switch (type) {
      case 'i64': return p.readS64().toString();
      case 'f32': return p.readFloat();
      case 'f64': return p.readDouble();
      case 'str': return p.readUtf8String();
      default: return p.readS32();
    }
  },
  count() { return results.length; },
  aob(pattern) {
    const hits = [];
    for (const r of Process.enumerateRanges('r--')) {
      try {
        Memory.scanSync(r.base, r.size, pattern, {
          onMatch(addr) { if (hits.length < 200) hits.push(addr.toString()); }
        });
      } catch (e) {}
    }
    return hits;
  }
};
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int)
    ap.add_argument("--name", default="No Man's Sky")
    ap.add_argument("--host")
    ap.add_argument("--usb", action="store_true", default=True)
    a = ap.parse_args()

    try:
        import frida
    except ImportError:
        print("缺少 frida:  pip install frida")
        return 1

    dev = frida.get_device_manager().add_remote_device(a.host) if a.host else frida.get_usb_device(3)
    if a.pid:
        session = dev.attach(a.pid)
    else:
        procs = [p for p in dev.enumerate_processes() if a.name.lower() in p.name.lower()]
        if not procs:
            print(f"没找到进程 {a.name}。先启动游戏，再 frida-ps -U 确认名字。")
            return 1
        print(f"attach -> {procs[0].name} (pid={procs[0].pid})")
        session = dev.attach(procs[0].pid)

    script = session.create_script(JS)
    script.load()
    ex = script.exports_sync
    print("已注入。输入 help 查看命令。\n")

    while True:
        try:
            line = input("nms> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        parts = line.split()
        c = parts[0].lower()
        try:
            if c in ("q", "quit", "exit"):
                break
            elif c == "help":
                print(__doc__)
            elif c == "modules":
                for m in ex.init():
                    print(f"  {m['base']:<18} {m['size']:>12,}  {m['name']}")
            elif c == "ranges":
                rs = ex.ranges(parts[1] if len(parts) > 1 else "rw-")
                print(f"共 {len(rs)} 段")
                for r in rs[:40]:
                    print(f"  {r['base']:<18} {r['size']:>12,}  {r['prot']}")
            elif c == "scan":
                n = ex.scan(int(parts[1]))
                print(f"命中 {n} 个地址")
            elif c == "scanf":
                print(f"剩余 {ex.filter_exact(int(parts[1]))} 个")
            elif c in ("changed", "unchanged", "inc", "dec"):
                print(f"剩余 {ex.filter_mode(c)} 个")
            elif c == "list":
                n = int(parts[1]) if len(parts) > 1 else 40
                for it in ex.list(n):
                    print(f"  {it['addr']:<18} = {it['value']}")
            elif c == "write":
                print(f"已写入 {ex.write(int(parts[1]))} 处")
            elif c == "writeat":
                print(f"写入成功，回读 = {ex.write_at(parts[1], int(parts[2]))}")
            elif c == "read":
                t = parts[2] if len(parts) > 2 else "i32"
                print(ex.read_at(parts[1], t))
            elif c == "aob":
                hits = ex.aob(" ".join(parts[1:]))
                print(f"命中 {len(hits)} 处")
                for h in hits[:20]:
                    print("  ", h)
            elif c == "stats":
                print(f"当前候选 {ex.count()}")
            else:
                print("未知命令，输入 help")
        except Exception as e:
            print("错误:", e)

    session.detach()
    return 0


if __name__ == "__main__":
    sys.exit(main())
