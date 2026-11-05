/**
 * Release-notes compatibility smoke test.
 *
 * Uses the same generator and Conventional Commits preset as semantic-release,
 * without pushing tags, creating releases, or requiring a GitHub token.
 */
import { generateNotes } from "@semantic-release/release-notes-generator";

const changes = [
  { hash: "a".repeat(40), message: "feat: demonstrate notification routing" },
  { hash: "b".repeat(40), message: "fix: protect application credentials" },
];

const notes = await generateNotes(
  { preset: "conventionalcommits" },
  {
    commits: changes,
    lastRelease: { version: "1.0.0", gitTag: "v1.0.0", gitHead: "0".repeat(40) },
    nextRelease: { version: "1.1.0", gitTag: "v1.1.0", gitHead: "1".repeat(40) },
    options: {
      repositoryUrl: "https://github.com/redoracle/hermes-plugin-gotify-notify.git",
    },
    cwd: process.cwd(),
  }
);

for (const heading of ["### Features", "### Bug Fixes"]) {
  if (!notes.includes(heading)) {
    throw new Error(`Release notes omitted expected section: ${heading}`);
  }
}

if (!notes.includes("notification routing") || !notes.includes("application credentials")) {
  throw new Error("Release notes omitted expected commit messages");
}
console.log("Conventional Commits release notes rendered with both sections");
