import enum
import pathlib
import subprocess


class GitStatus(enum.Enum):
    MATCH = 1
    CHANGED = 2
    NEEDS_STAGING = 3


def check_blessed_file_status(output_file_path: pathlib.Path) -> GitStatus:
    """Checks the Git status of the blessed file using porcelain format.

    Uses `git status --porcelain -- <file>` to check the status against the index.
    Does not catch subprocess errors (FileNotFoundError, CalledProcessError).

    Returns:
        The GitStatus enum.

    Raises:
        FileNotFoundError: If 'git' command is not found.
        subprocess.CalledProcessError: If git status command fails.
        ValueError: If the git status output is unexpected.
    """
    relative_path = str(output_file_path.relative_to(pathlib.Path.cwd()))

    # Check the status using porcelain format for the specific file
    command = ["git", "status", "--porcelain", "--", relative_path]
    # Run the command, letting exceptions (FileNotFoundError, CalledProcessError) bubble up
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=True,  # Will raise CalledProcessError on non-zero exit
        encoding="utf-8",
    )

    output = result.stdout

    # The first column is the staging area, the second is the working tree.
    # M = Modified
    # A = Added
    # ? = Untracked

    if not output:
        # No changes
        return GitStatus.MATCH
    elif output[1] == "?":
        # File is untracked
        return GitStatus.NEEDS_STAGING
    elif output[1] == " ":
        # No unstased changes
        return GitStatus.MATCH
    elif output[1] == "M":
        # Modified with unstaged changes
        return GitStatus.CHANGED
    else:
        # Any other output is unexpected for a single file check after writing it
        raise ValueError(
            f"Unexpected git status output for {relative_path}: '{output}'"
        )
