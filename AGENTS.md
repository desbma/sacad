# AGENTS.md

## Project Overview

**SACAD** (Smart Automatic Cover Art Downloader) - A Rust CLI tool to download album cover art.
Provides two binaries: `sacad` (single cover) and `sacad_r` (recursive library scan).

## Tech Stack

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
cargo test --all-features

# Run single binary
cargo run --bin sacad -- "artist" "album" 600 cover.jpg
cargo run --bin sacad_r -- /path/to/library 600 cover.jpg
```

## Project Structure

```
src/
├── bin/
│   ├── sacad.rs       # Single cover download binary
│   └── sacad_r.rs     # Recursive library scanner binary
├── source/            # Cover source implementations
├── http/              # HTTP client and caching
├── cl.rs              # CLI argument definitions
├── cover.rs           # Cover struct and comparison logic
├── extras.rs          # Man page and shell completion generation (feature-gated: generate-extras, unix only)
├── lib.rs             # Main library API, used by sacad and sacad_r binaries
├── perceptual_hash.rs # Image hashing for similarity
├── tags.rs            # Audio file tags handling
└── walk.rs            # Library tree walking and stat counters for sacad_r
```

## Code Style & Conventions

- Rust 2024 edition, MSRV 1.87 (can be increased as needed)
- Strict Clippy: pedantic + many restriction lints (see `[lints.clippy]` in Cargo.toml)
- No `unwrap`/`expect`/`panic` in non-test code; use `anyhow` for errors
- Imports:
  - Group std imports first, then external crates, then local modules
  - Never use fully-qualified paths (e.g., `std::path::Path` or `crate::ui::foo()`) in code; always import namespaces via `use` statements and refer to symbols by their short name
  - Import deep `std` namespaces aggressively (e.g., `use std::path::PathBuf;`, `use std::collections::HashMap;`), except for namespaces like `io` or `fs` whose symbols have very common names that may collide — import those at the module level instead (e.g., `use std::fs;`)
  - For third-party crates, prefer importing at the crate or module level (e.g., `use anyhow::Context as _;`, `use clap::Parser;`) rather than deeply importing individual symbols, to keep the origin of symbols clear when reading code — only import deeper when needed to avoid very long fully-qualified namespaces
- Prefer `log` macros for logging; no `dbg!` or `todo!`
- Prefer `default-features = false` for dependencies
- In tests:
  - Use `use super::*;` to import from the parent module
  - Prefer `unwrap()` over `expect()` for conciseness
  - Do not add custom messages to `assert!`/`assert_eq!`/`assert_ne!` — the test name is sufficient
  - Prefer full type comparisons with `assert_eq!` over selectively checking nested attributes or unpacking; tag types with `#[cfg_attr(test, derive(Eq, PartialEq))]` if needed
- Comments:
  - Documentation required: every module and item must have a doc comment (`//!` or `///`); `missing_docs` is warned
  - Comments do not end with a dot, unless it separates sentences
  - When moving or refactoring code, never remove comment lines — preserve all comments and move them along with the code they document

## Version control

- This repository uses the jujutsu VCS. **Never use any `jj` command that modifies the repository**.
- You can also use read-only git commands for inspecting repository state. **Never use any git command that modifies the repository**.
