"""
Simulated ML training application for image classification.

This application mimics a realistic deep learning training pipeline:
  load data → preprocess → build model → train (forward/backward) → evaluate

It is used to demonstrate GPU memory profiling with Inspektor Gadget.
"""

import os
import time
import gc

import torch
import torch.nn as nn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def print_memory(tag: str = ""):
    allocated = torch.cuda.memory_allocated() / (1024 ** 2)
    reserved = torch.cuda.memory_reserved() / (1024 ** 2)
    print(f"  [{tag:40s}]  allocated {allocated:8.1f} MB  |  reserved {reserved:8.1f} MB")


# ---------------------------------------------------------------------------
# Stage 1 – Data Loading
# ---------------------------------------------------------------------------

def load_images(num_samples, image_size):
    """Load training images from storage (simulated). ~460 MB."""
    images = torch.randn(num_samples, 3, image_size, image_size, device="cuda")
    print_memory("load_images")
    return images


def load_metadata(num_samples, image_size):
    """Load labels, bounding boxes & segmentation masks (simulated). ~8 MB."""
    labels = torch.randint(0, 1000, (num_samples,), device="cuda")
    bboxes = torch.randn(num_samples, 4, device="cuda")
    masks  = torch.randint(0, 2, (num_samples, image_size, image_size),
                           dtype=torch.uint8, device="cuda")
    print_memory("load_metadata")
    return labels, bboxes, masks


def load_dataset(num_samples=256, image_size=224):
    """Load images and metadata in parallel (simulated)."""
    print("\n── Stage 1: Loading dataset ──")
    images = load_images(num_samples, image_size)
    labels, bboxes, masks = load_metadata(num_samples, image_size)
    del bboxes, masks          # keep only labels for training
    torch.cuda.empty_cache()
    print_memory("load_dataset")
    time.sleep(15)
    return images, labels


# ---------------------------------------------------------------------------
# Stage 2 – Preprocessing
# ---------------------------------------------------------------------------

def compute_statistics(images):
    """Compute per-channel mean and std for normalization."""
    mean = images.mean(dim=(0, 2, 3), keepdim=True)
    std = images.std(dim=(0, 2, 3), keepdim=True) + 1e-5
    print_memory("compute_statistics")
    return mean, std


def normalize(images):
    """Normalize images to zero-mean, unit-variance. Allocates ~460 MB."""
    mean, std = compute_statistics(images)
    images = (images - mean) / std
    print_memory("normalize")
    return images


def apply_transformations(images):
    """Apply random augmentation transforms (simulated with noise). ~460 MB."""
    noise = torch.randn_like(images) * 0.05
    images = images + noise
    del noise
    print_memory("apply_transformations")
    return images


def augment_data(images):
    """Run the full augmentation sub-pipeline."""
    images = apply_transformations(images)
    print_memory("augment_data")
    return images


def build_feature_cache(images):
    """Pre-compute and cache spatial feature maps. ~128 MB."""
    pool = nn.AdaptiveAvgPool2d((16, 16)).cuda()
    features = pool(images)
    cache = features.clone()
    del features
    print_memory("build_feature_cache")
    return cache


def preprocess_data(images):
    """Preprocess: normalize, augment, and build feature cache."""
    print("\n── Stage 2: Preprocessing ──")
    images = normalize(images)             # branch 1: ~460 MB
    images = augment_data(images)          # branch 2: ~460 MB
    feature_cache = build_feature_cache(images)  # branch 3: ~128 MB
    del feature_cache  # consumed later; free for now
    torch.cuda.empty_cache()
    print_memory("preprocess_data")
    time.sleep(15)
    return images


# ---------------------------------------------------------------------------
# Stage 3 – Model construction
# ---------------------------------------------------------------------------

def init_attention_layers(embed_dim, num_heads, num_layers):
    """Stack multi-head self-attention layers."""
    layers = nn.ModuleList([
        nn.MultiheadAttention(embed_dim, num_heads, batch_first=True)
        for _ in range(num_layers)
    ]).cuda()
    print_memory("init_attention_layers")
    return layers


def create_encoder(embed_dim=512, num_heads=8, num_layers=6):
    """Build the encoder: patch embedding + attention layers."""
    patch_embed = nn.Conv2d(3, embed_dim, kernel_size=16, stride=16).cuda()
    attention = init_attention_layers(embed_dim, num_heads, num_layers)
    print_memory("create_encoder")
    return patch_embed, attention


def create_classifier_head(embed_dim=512, num_classes=1000):
    """Final linear classification head. ~2 MB."""
    head = nn.Linear(embed_dim, num_classes).cuda()
    print_memory("create_classifier_head")
    return head


def create_auxiliary_head(embed_dim=512, aux_classes=100):
    """Auxiliary head for multi-task learning (e.g. rotation prediction). ~0.2 MB."""
    aux = nn.Sequential(
        nn.Linear(embed_dim, embed_dim // 4),
        nn.ReLU(),
        nn.Linear(embed_dim // 4, aux_classes),
    ).cuda()
    print_memory("create_auxiliary_head")
    return aux


def build_model(embed_dim=512):
    """Assemble the full vision-transformer-style model."""
    print("\n── Stage 3: Building model ──")
    patch_embed, attention = create_encoder(embed_dim)  # branch 1: encoder
    head     = create_classifier_head(embed_dim)        # branch 2: main head
    aux_head = create_auxiliary_head(embed_dim)          # branch 3: aux head
    print_memory("build_model")
    time.sleep(15)
    return patch_embed, attention, head, aux_head


def allocate_momentum_buffers(params):
    """Allocate per-parameter momentum buffer (like SGD with momentum)."""
    buffers = [torch.zeros_like(p) for p in params]
    print_memory("allocate_momentum_buffers")
    return buffers


def allocate_variance_buffers(params):
    """Allocate per-parameter variance buffer (like Adam)."""
    buffers = [torch.zeros_like(p) for p in params]
    print_memory("allocate_variance_buffers")
    return buffers


def create_optimizer_state(patch_embed, attention, head):
    """Create persistent optimizer state that lives for the entire training."""
    print("\n── Stage 3b: Creating optimizer state ──")
    all_params = list(patch_embed.parameters()) + \
                 list(attention.parameters()) + \
                 list(head.parameters())
    momentum = allocate_momentum_buffers(all_params)
    variance = allocate_variance_buffers(all_params)
    print_memory("create_optimizer_state")
    time.sleep(15)
    return momentum, variance


# ---------------------------------------------------------------------------
# Stage 4 – Training
# ---------------------------------------------------------------------------

def forward_pass(images, patch_embed, attention_layers):
    """Run the forward pass through encoder layers."""
    x = patch_embed(images)                          # (B, embed, H', W')
    B, C, H, W = x.shape
    x = x.flatten(2).transpose(1, 2)                # (B, seq_len, embed)
    for layer in attention_layers:
        x, _ = layer(x, x, x)
    print_memory("forward_pass")
    return x


def compute_loss(logits, labels):
    """Compute cross-entropy loss."""
    loss_fn = nn.CrossEntropyLoss()
    loss = loss_fn(logits, labels)
    print_memory("compute_loss")
    return loss


def train_step(images, labels, patch_embed, attention, head):
    """Execute one full training step: forward → loss → backward.

    When ENABLE_BUG=1, allocates a ~1 GB gradient cache instead of a small
    buffer, simulating a real-world memory leak / over-allocation bug.
    """
    features = forward_pass(images, patch_embed, attention)
    logits = head(features.mean(dim=1))              # global average pool → classify
    logits.retain_grad()
    loss = compute_loss(logits, labels)

    if os.environ.get("ENABLE_BUG", "0") == "1":
        # ── Intentional bug: allocate ~1 GB instead of a few KB ──
        num_elements = 256 * 1024 * 1024  # 256M float32 elements ≈ 1 GB
    else:
        num_elements = 256
    oversized_cache = torch.randn(num_elements, device="cuda")
    loss.backward(retain_graph=True)
    print_memory("train_step")
    return loss, oversized_cache


def train(images, labels, patch_embed, attention, head,
          optimizer_state, epochs=3, batch_size=32):
    """Training loop over multiple epochs and batches."""
    print("\n── Stage 4: Training ──")
    num_samples = images.size(0)
    momentum, variance = optimizer_state

    # BUG: gradient caches are accumulated and never freed → memory leak
    gradient_history = []

    for epoch in range(epochs):
        print(f"\n  Epoch {epoch + 1}/{epochs}")
        for start in range(0, num_samples, batch_size):
            end = min(start + batch_size, num_samples)
            batch_images = images[start:end]
            batch_labels = labels[start:end]

            loss, grad_cache = train_step(
                batch_images, batch_labels, patch_embed, attention, head
            )
            # BUG: appending instead of releasing — the leak grows each step
            gradient_history.append(grad_cache)
            print(f"    batch [{start}:{end}]  loss={loss.item():.4f}")
            print(f"    gradient_history size: {len(gradient_history)} entries")
            time.sleep(1)

        print_memory(f"epoch {epoch + 1} done")
        time.sleep(2)

    # Hold at peak memory for 3 minutes
    print(f"\n  Holding peak memory for 3 minutes …")
    print_memory("peak hold")
    time.sleep(180)

    # Leak is finally freed here, but in a real app this list would survive
    print(f"  Leaked {len(gradient_history)} gradient caches during training")
    del gradient_history
    torch.cuda.empty_cache()
    print_memory("train")


# ---------------------------------------------------------------------------
# Stage 5 – Evaluation
# ---------------------------------------------------------------------------

def run_inference(images, patch_embed, attention, head, batch_size=64):
    """Run forward inference on full dataset. Allocates activations per batch."""
    all_preds = []
    num_samples = images.size(0)
    with torch.no_grad():
        for start in range(0, num_samples, batch_size):
            end = min(start + batch_size, num_samples)
            features = forward_pass(images[start:end], patch_embed, attention)
            logits = head(features.mean(dim=1))
            all_preds.append(logits)
    predictions = torch.cat(all_preds, dim=0)
    print_memory("run_inference")
    return predictions


def compute_metrics(predictions, labels):
    """Compute accuracy and per-class confidence. ~1 MB."""
    correct = (predictions.argmax(dim=1) == labels).float().mean()
    confidence = torch.softmax(predictions, dim=1)
    print_memory("compute_metrics")
    return correct.item(), confidence


def evaluate(images, labels, patch_embed, attention, head):
    """Run evaluation: inference then metrics (two sibling branches)."""
    print("\n── Stage 5: Evaluation ──")
    predictions = run_inference(images, patch_embed, attention, head)  # branch 1
    accuracy, confidence = compute_metrics(predictions, labels)       # branch 2
    print(f"  Accuracy: {accuracy * 100:.1f}%")
    del confidence, predictions
    torch.cuda.empty_cache()
    print_memory("evaluate")
    return accuracy


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline():
    """End-to-end ML pipeline: data → preprocess → model → train → eval."""
    images, labels = load_dataset(num_samples=256, image_size=224)
    images = preprocess_data(images)
    patch_embed, attention, head, aux_head = build_model()
    optimizer_state = create_optimizer_state(patch_embed, attention, head)
    train(images, labels, patch_embed, attention, head,
          optimizer_state, epochs=2, batch_size=32)
    evaluate(images, labels, patch_embed, attention, head)

    # Cleanup
    del images, labels, patch_embed, attention, head, aux_head, optimizer_state
    gc.collect()
    torch.cuda.empty_cache()
    print_memory("pipeline cleanup")


def main():
    print("=" * 60)
    print("  Image Classification Training Pipeline")
    print("=" * 60)
    print(f"  PID  : {os.getpid()}")

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available – a GPU is required.")

    gpu = torch.cuda.get_device_name(torch.cuda.current_device())
    total = torch.cuda.get_device_properties(0).total_memory / (1024 ** 2)
    print(f"  GPU  : {gpu}")
    print(f"  VRAM : {total:.0f} MB")
    print()

    # Give time for profilers / sidecars to attach
    time.sleep(10)

    while True:
        run_pipeline()
        print("\n  Sleeping before next run …\n")
        time.sleep(5)


if __name__ == "__main__":
    main()
