# AGENTS.md

## Project Overview

**SACAD** (Smart Automatic Cover Art Downloader) - A Rust CLI tool to download album cover art.
Provides two binaries: `sacad` (single cover) and `sacad_r` (recursive library scan).

## Tech Stack

- **Language**: Rust (Edition 2024, MSRV 1.87)
- **Async runtime**: Tokio
- **HTTP client**: reqwest
- **Image processing**: image crate, blockhash (perceptual hashing)
- **CLI parsing**: clap (derive)

## Common Commands

```bash
# Build
cargo build
cargo build --release

# Check (fast type/lint check)
cargo check

# Run clippy (strict linting enabled in Cargo.toml)
cargo clippy --all-targets

# Format code
cargo +nightly fmt -- --config imports_granularity=Crate --config group_imports=StdExternalCrate

# Run tests
cargo test

# Run single binary
cargo run --bin sacad -- "artist" "album" 600 cover.jpg
cargo run --bin sacad_r -- /path/to/library 600 cover.jpg
```

## Project Structure

```
src/
├── bin/
│   ├── sacad.rs      # Single cover download binary
│   └── sacad_r.rs    # Recursive library scanner binary
├── source/           # Cover source implementations (Deezer, Discogs, Last.fm, iTunes)
├── http/             # HTTP client and caching
├── cl.rs             # CLI argument definitions
├── cover.rs          # Cover struct and comparison logic
├── lib.rs            # Main library API
└── perceptual_hash.rs # Image hashing for similarity
```

## Code Style & Conventions

- **No unsafe code**: `unsafe_code = "forbid"` enforced
- **Strict clippy**: pedantic + many restriction lints enabled (see `Cargo.toml` `[lints.clippy]`)
- **Documentation required**: `missing_docs` warnings
- **Error handling**: Use `anyhow` for errors, avoid `.unwrap()` and `.expect()` outside tests
- **Indexing**: Avoid direct indexing (`[]`), use `.get()` instead (outside tests)
- **Tests**: `expect`, `unwrap`, `panic`, indexing are allowed in tests (see `clippy.toml`)

## Pre-commit Hooks

Uses pre-commit with:

- `cargo check`, `clippy`, `fmt`
- shellcheck
- conventional commits
