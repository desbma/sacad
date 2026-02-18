//! Man page and shell completion generation

use std::path::Path;

use clap::{CommandFactory, ValueEnum as _};
use clap_complete::Shell;

/// Generate man pages into the target directory
pub fn generate_man_pages<C: CommandFactory>(name: &'static str, dir: &Path) -> anyhow::Result<()> {
    let cmd = C::command().name(name);
    clap_mangen::generate_to(cmd, dir)?;
    Ok(())
}

/// Generate all shell completions into the target directory
pub fn generate_shell_completions<C: CommandFactory>(
    name: &'static str,
    dir: &Path,
) -> anyhow::Result<()> {
    let mut cmd = C::command().name(name);
    for shell in Shell::value_variants() {
        clap_complete::generate_to(*shell, &mut cmd, name, dir)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::fs;

    use super::*;
    use crate::cl;

    #[test]
    fn man_pages_generated() {
        let dir = tempfile::tempdir().unwrap();
        generate_man_pages::<cl::SacadArgs>("sacad", dir.path()).unwrap();
        let entries: Vec<_> = fs::read_dir(dir.path()).unwrap().collect();
        assert!(!entries.is_empty());
        for entry in entries {
            let path = entry.unwrap().path();
            assert!(path.extension().is_some_and(|e| e == "1"));
            let content = fs::read_to_string(&path).unwrap();
            assert!(!content.is_empty());
        }
    }

    #[test]
    fn man_pages_use_provided_name() {
        let dir = tempfile::tempdir().unwrap();
        generate_man_pages::<cl::SacadRecursiveArgs>("sacad_r", dir.path()).unwrap();
        for entry in fs::read_dir(dir.path()).unwrap() {
            let path = entry.unwrap().path();
            assert!(
                path.file_name()
                    .unwrap()
                    .to_str()
                    .unwrap()
                    .starts_with("sacad_r")
            );
            let content = fs::read_to_string(&path).unwrap();
            // roff escapes underscores/hyphens; check .TH header uses the provided name
            assert!(content.contains(".TH sacad_r "));
        }
    }

    #[test]
    fn shell_completions_generated() {
        let dir = tempfile::tempdir().unwrap();
        generate_shell_completions::<cl::SacadArgs>("sacad", dir.path()).unwrap();
        let entries: Vec<_> = fs::read_dir(dir.path()).unwrap().collect();
        assert!(!entries.is_empty());
        for entry in entries {
            let content = fs::read_to_string(entry.unwrap().path()).unwrap();
            assert!(!content.is_empty());
        }
    }

    #[test]
    fn shell_completions_use_provided_name() {
        let dir = tempfile::tempdir().unwrap();
        generate_shell_completions::<cl::SacadRecursiveArgs>("sacad_r", dir.path()).unwrap();
        for entry in fs::read_dir(dir.path()).unwrap() {
            let path = entry.unwrap().path();
            let file_name = path.file_name().unwrap().to_str().unwrap();
            assert!(file_name.contains("sacad_r"));
            let content = fs::read_to_string(&path).unwrap();
            assert!(content.contains("sacad_r"));
        }
    }
}
