"""Explicit real Windows playback/capture acceptance harness (never imported by app).

Run from project root: .venv/Scripts/python tools/live_checks.py --output PATH --seconds 600
Output must be a NEW directory. This starts audible VLC and WinMM test tones.
"""
from __future__ import annotations

import argparse
import ctypes as ct
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.main import generate_tones


class Player:
    def __init__(self, vlc: Path, tone: Path, log: Path, ready_timeout: float = 10):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.log = log.open("xb")
        self.child = subprocess.Popen([str(vlc), "--intf", "dummy", "--extraintf", "rc", "--rc-quiet",
                                       "--rc-host", f"127.0.0.1:{port}", "--ignore-config", "--no-one-instance",
                                       "--no-video", "--loop", str(tone)], stdout=self.log, stderr=self.log,
                                      creationflags=subprocess.CREATE_NO_WINDOW)
        self.control = None
        try:
            deadline = time.monotonic() + ready_timeout
            while time.monotonic() < deadline and self.child.poll() is None:
                try:
                    self.control = socket.create_connection(("127.0.0.1", port), timeout=0.2)
                    self.control.settimeout(1)
                    break
                except OSError:
                    time.sleep(0.1)
            if self.control is None:
                raise RuntimeError("VLC RC interface did not start")
            time.sleep(1)
        except BaseException:
            self.close()
            raise

    def command(self, command: str):
        self.control.sendall((command + "\n").encode("ascii"))

    def close(self):
        if self.control:
            self.control.close()
            self.control = None
        if self.child.poll() is None:
            self.child.terminate()
            self.child.wait(timeout=5)
        self.log.close()


class Run:
    def __init__(self, output: Path, name: str, player: Player, seconds: float, extra=()):
        self.path = output / f"{name}.jsonl"
        self.file = self.path.open("xb")
        self.error = (output / f"{name}.stderr.txt").open("xb")
        self.child = subprocess.Popen([sys.executable, "-m", "app.main", "capture", "--pid", str(player.child.pid),
                                       "--seconds", str(seconds), *extra], cwd=ROOT, stdout=self.file, stderr=self.error,
                                      creationflags=subprocess.CREATE_NO_WINDOW)

    def finish(self, timeout=30):
        try:
            code = self.child.wait(timeout=timeout)
        finally:
            if self.child.poll() is None:
                self.child.terminate()
                self.child.wait(timeout=5)
            self.file.close()
            self.error.close()
        rows = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]
        return {"exit_code": code, "summaries": [r for r in rows if r["event"] == "capture_summary"],
                "errors": [r for r in rows if r["event"] in ("error", "native_error")],
                "diagnostics": [r for r in rows if r["event"] == "audio_diagnostics"],
                "native_status": [r for r in rows if r["event"] == "native_status"]}


def verify_results(results: dict, seconds: int) -> dict:
    """Evidence-based checks; a normal CLI stop alone does not validate pause/resume."""
    c = results["C"]
    previous_n = 0
    previous_energy = 0.0
    quiet, resumed = [], []
    for row in c["diagnostics"]:
        n = row["samples"]
        energy = n * row["rms"] ** 2
        interval_rms = (max(0, energy - previous_energy) / max(1, n - previous_n)) ** 0.5
        previous_n, previous_energy = n, energy
        t = row["monotonic_ns"]
        if c["pause_requested_ns"] + 1_500_000_000 < t < c["resume_requested_ns"]:
            quiet.append(interval_rms)
        if t > c["resume_requested_ns"] + 1_500_000_000:
            resumed.append(interval_rms)
    ab = results["A_B"]["summaries"][-1]
    return {"A_B": results["A_B"]["exit_code"] == 0 and ab["isolation_pass"] and ab["audio_seconds"] >= seconds - 1,
            "C": c["exit_code"] == 0 and bool(quiet) and max(quiet) < 1e-4 and bool(resumed) and min(resumed) > 0.01,
            "D": results["D"]["exit_code"] != 0 and any("target_exited" in str(e) for e in results["D"]["errors"]),
            "E": results["E"]["exit_code"] == 0 and len(results["E"]["summaries"]) == 10
                  and all(r["complete"] and r["signal_detected"] for r in results["E"]["summaries"])}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--vlc", type=Path, default=ROOT / "tools/vlc-3.0.24/vlc.exe")
    p.add_argument("--seconds", type=int, default=600)
    args = p.parse_args()
    if args.seconds < 5 or not args.vlc.is_file():
        p.error("need VLC and --seconds >= 5")
    args.output.mkdir(parents=True, exist_ok=False)
    fixtures = args.output / "fixtures"
    fixtures.mkdir()
    generate_tones(fixtures, max(60, args.seconds + 10))
    players, long_run = [], None
    interference = None
    results = {}
    try:
        target = Player(args.vlc.resolve(), (fixtures / "tone-1000hz.wav").resolve(), args.output / "vlc-target.txt")
        players.append(target)
        # Real other-application rendering: Windows PlaySound in a separate Python process.
        interference = subprocess.Popen([sys.executable, "-c",
            "import winsound,sys; winsound.PlaySound(sys.argv[1],winsound.SND_FILENAME|winsound.SND_ASYNC|winsound.SND_LOOP|winsound.SND_NODEFAULT); print('WinMM_started',flush=True); sys.stdin.readline(); winsound.PlaySound(None,0)",
            str((fixtures / "tone-440hz.wav").resolve())], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        if interference.stdout.readline().strip() != "WinMM_started":
            raise RuntimeError("interference renderer did not start")
        results["interference"] = {"application": "Python winsound / Windows WinMM PlaySound", "pid": interference.pid,
                                   "hz": 440, "render_api_started": True}
        long_run = Run(args.output, "A_B_continuous_isolation", target, args.seconds, ["--isolation"])
        print("Long capture running", flush=True)
        # Separate VLC tests run while 1000 Hz + 440 Hz continue in OTHER processes.
        life = Player(args.vlc.resolve(), (fixtures / "tone-1000hz.wav").resolve(), args.output / "vlc-lifecycle.txt")
        players.append(life)
        pause_run = Run(args.output, "C_pause_resume", life, 12)
        time.sleep(3)
        life.command("pause")
        pause_start = time.monotonic_ns()
        time.sleep(4)
        # VLC 3.x RC requires pause again to resume; play does not resume.
        life.command("pause")
        resume = time.monotonic_ns()
        results["C"] = pause_run.finish()
        results["C"]["pause_requested_ns"] = pause_start
        results["C"]["resume_requested_ns"] = resume
        exit_run = Run(args.output, "D_target_exit", life, 30)
        time.sleep(3)
        exit_at = time.monotonic()
        life.close()
        results["D"] = exit_run.finish()
        results["D"]["exit_detection_and_cleanup_seconds"] = time.monotonic() - exit_at
        fresh = Player(args.vlc.resolve(), (fixtures / "tone-1000hz.wav").resolve(), args.output / "vlc-restarted.txt")
        players.append(fresh)
        results["D"]["old_pid"] = life.child.pid
        results["D"]["new_pid"] = fresh.child.pid
        results["E"] = Run(args.output, "E_ten_cycles", fresh, 2, ["--cycles", "10"]).finish(timeout=90)
        print("Lifecycle checks finished; waiting for long capture", flush=True)
        results["A_B"] = long_run.finish(timeout=args.seconds + 30)
        long_run = None
        results["verified"] = verify_results(results, args.seconds)
    finally:
        if long_run and long_run.child.poll() is None:
            long_run.child.terminate()
            long_run.child.wait(timeout=5)
        for player in players:
            player.close()
        if interference:
            if interference.poll() is None:
                interference.communicate("stop\n", timeout=5)
            else:
                interference.communicate(timeout=5)
        (args.output / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: {"exit_code": v.get("exit_code"), "summaries": v.get("summaries")} for k,v in results.items()}, ensure_ascii=False), flush=True)
    return 0 if all(results["verified"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
