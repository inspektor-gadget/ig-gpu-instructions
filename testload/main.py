"""
Test PyTorch application that allocates GPU memory in various patterns.
Useful for testing CUDA memory profilers (e.g. Inspektor Gadget cuda_memory_metrics).

Usage:
    python main.py [--duration SECONDS] [--interval SECONDS] [--max-mb MB]
"""

import argparse
import time
import gc

import torch


def check_gpu():
    """Verify CUDA is available and print device info."""
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available. This test requires a GPU.")
    device = torch.cuda.current_device()
    name = torch.cuda.get_device_name(device)
    total_mem = torch.cuda.get_device_properties(device).total_memory / (1024 ** 2)
    print(f"[info] GPU: {name} | Total memory: {total_mem:.0f} MB")
    return device


def print_memory(tag: str = ""):
    """Print current GPU memory usage."""
    allocated = torch.cuda.memory_allocated() / (1024 ** 2)
    reserved = torch.cuda.memory_reserved() / (1024 ** 2)
    print(f"[mem] {tag:30s} | allocated: {allocated:8.1f} MB | reserved: {reserved:8.1f} MB")


def steady_allocation(size_mb: int, hold_seconds: float):
    """Allocate a single tensor of a given size and hold it."""
    print(f"\n=== Steady allocation: {size_mb} MB for {hold_seconds}s ===")
    numel = size_mb * 1024 * 1024 // 4  # float32 = 4 bytes
    tensor = torch.randn(numel, device="cuda")
    print_memory("after alloc")
    time.sleep(hold_seconds)
    del tensor
    torch.cuda.empty_cache()
    print_memory("after free")


def incremental_allocation(step_mb: int, steps: int, interval: float):
    """Allocate memory in incremental steps, then free everything."""
    print(f"\n=== Incremental allocation: {steps} steps × {step_mb} MB ===")
    tensors = []
    numel = step_mb * 1024 * 1024 // 4
    for i in range(steps):
        tensors.append(torch.randn(numel, device="cuda"))
        print_memory(f"step {i + 1}/{steps}")
        time.sleep(interval)

    print(f"[info] Holding {len(tensors)} tensors for 2s ...")
    time.sleep(2)

    # Free in reverse order
    for i in range(len(tensors) - 1, -1, -1):
        del tensors[i]
        torch.cuda.empty_cache()
        print_memory(f"freed step {i + 1}")
        time.sleep(interval / 2)
    tensors.clear()


def sawtooth_allocation(size_mb: int, cycles: int, interval: float):
    """Repeatedly allocate and free memory to create a sawtooth pattern."""
    print(f"\n=== Sawtooth allocation: {cycles} cycles × {size_mb} MB ===")
    numel = size_mb * 1024 * 1024 // 4
    for i in range(cycles):
        tensor = torch.randn(numel, device="cuda")
        print_memory(f"cycle {i + 1} alloc")
        time.sleep(interval)
        del tensor
        torch.cuda.empty_cache()
        print_memory(f"cycle {i + 1} free")
        time.sleep(interval)


def mixed_sizes_allocation(interval: float):
    """Allocate tensors of various sizes simultaneously."""
    print("\n=== Mixed sizes allocation ===")
    sizes_mb = [8, 32, 64, 128, 256]
    tensors = {}
    for mb in sizes_mb:
        numel = mb * 1024 * 1024 // 4
        tensors[mb] = torch.randn(numel, device="cuda")
        print_memory(f"allocated {mb} MB")
        time.sleep(interval)

    print("[info] Holding all tensors for 3s ...")
    time.sleep(3)

    # Free smallest first
    for mb in sizes_mb:
        del tensors[mb]
        torch.cuda.empty_cache()
        print_memory(f"freed {mb} MB")
        time.sleep(interval / 2)


def matmul_workload(size: int, iterations: int, interval: float):
    """Run matrix multiplications to generate compute + memory activity."""
    print(f"\n=== Matmul workload: {size}×{size} for {iterations} iterations ===")
    a = torch.randn(size, size, device="cuda")
    b = torch.randn(size, size, device="cuda")
    print_memory("matrices allocated")

    for i in range(iterations):
        c = torch.mm(a, b)
        if i % max(1, iterations // 5) == 0:
            print_memory(f"iter {i + 1}/{iterations}")
        time.sleep(interval)

    del a, b, c
    torch.cuda.empty_cache()
    print_memory("after cleanup")


def main():
    parser = argparse.ArgumentParser(description="GPU memory allocation test for profiler testing")
    parser.add_argument("--duration", type=int, default=0,
                        help="Run in a loop for this many seconds (0 = run once)")
    parser.add_argument("--interval", type=float, default=1.0,
                        help="Sleep interval between operations (seconds)")
    parser.add_argument("--max-mb", type=int, default=256,
                        help="Maximum single allocation size in MB")
    args = parser.parse_args()

    device = check_gpu()
    print_memory("baseline")

    start = time.time()
    iteration = 0

    while True:
        iteration += 1
        print(f"\n{'=' * 60}")
        print(f"  Iteration {iteration}  (elapsed: {time.time() - start:.0f}s)")
        print(f"{'=' * 60}")

        # 1. Steady allocation
        steady_allocation(args.max_mb, hold_seconds=3)

        # 2. Incremental staircase
        step = max(8, args.max_mb // 8)
        incremental_allocation(step_mb=step, steps=8, interval=args.interval)

        # 3. Sawtooth pattern
        sawtooth_allocation(size_mb=args.max_mb // 2, cycles=5, interval=args.interval)

        # 4. Mixed sizes
        mixed_sizes_allocation(interval=args.interval)

        # 5. Compute workload
        matmul_workload(size=2048, iterations=20, interval=args.interval / 2)

        # Final cleanup
        gc.collect()
        torch.cuda.empty_cache()
        print_memory("end of iteration")

        if args.duration <= 0:
            break
        if time.time() - start >= args.duration:
            print(f"\n[info] Duration limit reached ({args.duration}s). Exiting.")
            break

    print("\n[done] Test completed.")


if __name__ == "__main__":
    main()
