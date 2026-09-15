# host/run_tests.py
import argparse
import csv
import statistics
import time
from datetime import datetime
from pathlib import Path

import serial


def open_port(port: str, baud: int = 115200, timeout: float = 1.0) -> serial.Serial:
    ser = serial.Serial(port, baudrate=baud, timeout=timeout)
    time.sleep(2)
    ser.reset_input_buffer()
    return ser


def send_command(ser: serial.Serial, cmd: str) -> tuple[str, float]:
    t0 = time.perf_counter()
    ser.write((cmd + "\n").encode())
    resp = ser.readline().decode(errors="replace").strip()
    t1 = time.perf_counter()
    round_trip_us = (t1 - t0) * 1_000_000
    return resp, round_trip_us


def parse_toggle_response(line: str) -> tuple[int, int]:
    parts = line.split()
    if len(parts) != 4 or parts[0] != "LATENCY_NS" or parts[2] != "CYCLES":
        raise ValueError(f"Unexpected TOGGLE response: {line!r}")
    return int(parts[1]), int(parts[3])


def run_toggle_test(ser: serial.Serial, iters: int) -> dict:
    latency_ns, round_trip_us = [], []
    for _ in range(iters):
        resp, rt_us = send_command(ser, "TOGGLE")
        ns, _cycles = parse_toggle_response(resp)
        latency_ns.append(ns)
        round_trip_us.append(rt_us)
    return {"latency_ns": latency_ns, "round_trip_us": round_trip_us}


def run_ping_toggle_comparison(ser: serial.Serial, iters: int) -> dict:
    deltas = []
    for _ in range(iters):
        _, rt_ping = send_command(ser, "PING")
        _, rt_toggle = send_command(ser, "TOGGLE")
        deltas.append(rt_toggle - rt_ping)
    return {"deltas_us": deltas}


def summarize(samples: list[float]) -> dict:
    return {
        "min": min(samples), "max": max(samples),
        "mean": statistics.mean(samples), "stdev": statistics.pstdev(samples),
    }


def write_csv(path: Path, latency_ns, round_trip_us) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["iteration", "latency_ns", "round_trip_us"])
        for i, (ns, rt) in enumerate(zip(latency_ns, round_trip_us)):
            w.writerow([i, ns, f"{rt:.1f}"])


def write_delta_csv(path: Path, deltas: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["iteration", "ping_toggle_delta_us"])
        for i, d in enumerate(deltas):
            w.writerow([i, f"{d:.1f}"])


def write_summary(path: Path, iters, lat_stats, rt_stats, delta_stats,
                   pass_max_ns, result_pass) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(f"Generated: {datetime.now().isoformat(timespec='seconds')}\n")
        f.write(f"Iterations: {iters}\n\n")
        f.write("On-chip latency (DWT-measured, ns):\n")
        f.write(f"  min={lat_stats['min']} max={lat_stats['max']} "
                f"mean={lat_stats['mean']:.1f} stdev={lat_stats['stdev']:.1f}\n\n")
        f.write("Round-trip latency (host perf_counter, us):\n")
        f.write(f"  min={rt_stats['min']:.1f} max={rt_stats['max']:.1f} "
                f"mean={rt_stats['mean']:.1f} stdev={rt_stats['stdev']:.1f}\n\n")
        f.write("PING vs TOGGLE round-trip delta (us) - isolates UART byte-transmission cost:\n")
        f.write(f"  mean={delta_stats['mean']:.1f} stdev={delta_stats['stdev']:.1f} "
                f"min={delta_stats['min']:.1f} max={delta_stats['max']:.1f}\n")
        if pass_max_ns is not None:
            f.write(f"\nPass threshold (on-chip max): {pass_max_ns} ns\n")
            f.write(f"RESULT: {'PASS' if result_pass else 'FAIL'}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--iters", type=int, default=1000)
    ap.add_argument("--delta-iters", type=int, default=100,
                     help="Samples for the PING/TOGGLE byte-cost comparison")
    ap.add_argument("--pass-max-ns", type=int, default=None,
                     help="Omit on first run — establish a baseline before setting a threshold")
    args = ap.parse_args()

    ser = open_port(args.port)
    resp, _ = send_command(ser, "PING")
    if resp != "OK":
        raise RuntimeError(f"PING failed, got: {resp!r}")

    result = run_toggle_test(ser, args.iters)
    delta_result = run_ping_toggle_comparison(ser, args.delta_iters)
    ser.close()

    lat_stats = summarize(result["latency_ns"])
    rt_stats = summarize(result["round_trip_us"])
    delta_stats = summarize(delta_result["deltas_us"])

    result_pass = None
    if args.pass_max_ns is not None:
        result_pass = lat_stats["max"] <= args.pass_max_ns

    reports_dir = Path("reports")
    write_csv(reports_dir / "latency.csv", result["latency_ns"], result["round_trip_us"])
    write_delta_csv(reports_dir / "ping_toggle_delta.csv", delta_result["deltas_us"])
    write_summary(reports_dir / "summary.txt", args.iters, lat_stats, rt_stats,
                  delta_stats, args.pass_max_ns, result_pass)

    print(f"On-chip:    min={lat_stats['min']} max={lat_stats['max']} mean={lat_stats['mean']:.1f} ns")
    print(f"Round-trip: min={rt_stats['min']:.1f} max={rt_stats['max']:.1f} mean={rt_stats['mean']:.1f} us")
    print(f"PING/TOGGLE delta: mean={delta_stats['mean']:.1f} stdev={delta_stats['stdev']:.1f} us")
    if result_pass is not None:
        print(f"RESULT: {'PASS' if result_pass else 'FAIL'}")


if __name__ == "__main__":
    main()