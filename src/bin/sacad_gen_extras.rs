//! Generate man pages and shell completions for sacad binaries

#[cfg(unix)]
use std::path::PathBuf;

#[cfg(unix)]
use clap::{Parser, Subcommand};
#[cfg(unix)]
use sacad::{cl, extras};

/// Generate man pages and shell completions for sacad binaries
#[cfg(unix)]
#[derive(Parser, Debug)]
#[command(version, about)]
struct Args {
    /// Command to run
    #[command(subcommand)]
    command: Command,
}

/// Generation command
#[cfg(unix)]
#[derive(Subcommand, Debug)]
enum Command {
    /// Generate man pages
    GenManPages {
        /// Target directory (must exist)
        dir: PathBuf,
    },

    /// Generate shell completions
    GenShellCompletions {
        /// Target directory (must exist)
        dir: PathBuf,
    },
}

#[cfg(unix)]
fn main() -> anyhow::Result<()> {
    let args = Args::parse();

    match args.command {
        Command::GenManPages { dir } => {
            extras::generate_man_pages::<cl::SacadArgs>("sacad", &dir)?;
            extras::generate_man_pages::<cl::SacadRecursiveArgs>("sacad_r", &dir)?;
        }
        Command::GenShellCompletions { dir } => {
            extras::generate_shell_completions::<cl::SacadArgs>("sacad", &dir)?;
            extras::generate_shell_completions::<cl::SacadRecursiveArgs>("sacad_r", &dir)?;
        }
    }

    Ok(())
}

#[cfg(not(unix))]
fn main() {}

#[expect(clippy::tests_outside_test_module)]
#[cfg(all(test, unix))]
mod tests {
    use clap::CommandFactory as _;

    use super::*;

    #[test]
    fn verify_cli() {
        Args::command().debug_assert();
    }

    #[test]
    fn gen_man_pages() {
        let result = Args::try_parse_from(["sacad_gen_extras", "gen-man-pages", "/tmp"]);
        assert!(result.is_ok());
    }

    #[test]
    fn gen_shell_completions() {
        let result = Args::try_parse_from(["sacad_gen_extras", "gen-shell-completions", "/tmp"]);
        assert!(result.is_ok());
    }

    #[test]
    fn gen_shell_completions_rejects_no_args() {
        let result = Args::try_parse_from(["sacad_gen_extras", "gen-shell-completions"]);
        assert!(result.is_err());
    }
}
