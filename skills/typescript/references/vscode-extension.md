# VS Code extensions

What a VS Code extension adds to the `typescript` skill. The skill's rules all still
apply; this covers the extension host, the manifest and the release.

## Module format, floor and types

- **Ship a CommonJS bundle** unless `engines.vscode` is already at least 1.100, the
  release that let the Node extension host load ESM, and the extension has no `browser`
  entry. The web extension host did not gain ESM in that release, so check the release
  notes before emitting ESM for it.
- **For a CommonJS bundle, the tsconfig models CommonJS**: `module: commonjs`,
  `moduleResolution: bundler`, `isolatedModules`, and `verbatimModuleSyntax` off (see
  the skill's *Compiler configuration*).
- **Pin `@types/vscode` to the `engines.vscode` floor**, exact or `~`. A newer types
  package lets code compile against API the floor's users don't have, and `vsce`
  refuses to package when the types version is ahead of the engine.
- **Raise the floor deliberately, never as a side effect.** Before upgrading a
  dependency such as `vscode-languageclient`, read its own `engines.vscode`: a major
  that requires a newer editor raises the extension's floor with it. Use the newest
  major whose floor fits, and record why when you stay on an older one.

## Bundling

- **Bundle with esbuild**: `platform: "node"`, the output format matching the
  manifest, and `external: ["vscode"]`. The host injects `vscode`; anything else marked
  external needs a runtime reason, such as a native or dynamically loaded package.
- **Type-check separately** with `tsc --noEmit`, since esbuild strips types without
  checking them.
- **Check that the built entry point activates in the extension host**, not just that
  the bundle builds — a missing external or an ESM-only dependency fails only at load.

## Testing

- **Keep logic that doesn't need the `vscode` API out of modules that import it**, so it
  runs as plain unit tests. Exercise the code that does need it in the real extension
  host with `@vscode/test-cli` (`vscode-test`) and Mocha, which is the runner it drives.
  Don't mock the `vscode` module: a hand-written fake of the API tests the fake.
- **Unit tests for the vscode-free code can be a second labelled configuration in the
  same `.vscode-test.*` file** when the extension is small; a separate Vitest suite
  earns its place once that code grows.
- **Run the host under `xvfb-run -a` on headless Linux CI.** Without a display the
  host fails to start, which reads like a test failure.
- **Collect coverage with `vscode-test --coverage`** (V8 via c8;
  `--coverage-reporter` and `--coverage-output` set the format and directory).
- **Test trust states as separate configurations.** The host cannot toggle Workspace
  Trust during a run, so a trusted run and an untrusted run with its own
  `--user-data-dir` are two configurations, not one test.
- **Test the `engines.vscode` floor as well as stable.** `vscode-test` takes a
  `version`, so add a floor configuration in CI; otherwise the advertised minimum is
  never run.
- **Give each end-to-end test its own fixture files.** The host shares one workspace
  across a run, so a test that edits a shared file changes the next test's input.

## Promise safety

- **Keep `checkThenables: true` on `no-floating-promises`** (oxlint and
  typescript-eslint both take it; the skill's oxlint config sets it). The `vscode`
  API returns `Thenable`, not `Promise`, and the rule skips non-`Promise` thenables
  by default. A floating `window.showInformationMessage(...)`
  or `commands.executeCommand(...)` goes unreported without it.

## Manifest

- **Declare `capabilities.untrustedWorkspaces` and `virtualWorkspaces` explicitly** for
  an extension that runs a process or reads the workspace from disk. Start from
  `supported: false`. Move to `"limited"` only with `restrictedConfigurations` covering
  every setting that names an executable, a path or arguments — those are how a
  workspace gets its own code run.
- **No `browser` entry without a real web implementation.** The web host has no Node
  APIs and cannot spawn a process, so a Node extension's code does not run there.
- **Activate on the events that need the extension**, a language or a workspace file,
  not `*`.
- **An extension that runs a native tool beside the workspace sets `extensionKind:
  ["workspace"]`**, so in remote development it runs where the files and the binary are.

## Language clients

- **Await `client.start()`, and return `client.stop()` from `deactivate`**, so the
  server shuts down before the host does.
- **Give users a restart command and an `<id>.trace.server` setting
  (`off` / `messages` / `verbose`)**, and cap automatic restarts so a server that keeps
  crashing stops respawning.
- **New code serves settings through `workspace/configuration`, not
  `synchronize.configurationSection`**, which the client deprecates because one pushed
  object cannot represent resource-scoped settings.

## Native binaries and release

- **An extension that bundles a native binary publishes one VSIX per platform** with
  `vsce package --target <target>`, each holding only its own binary. The binary
  location and the target list change together; treat either as a release change.
- **Resolve the binary deterministically**: an explicit user setting first, then the
  bundled copy, with any `PATH` lookup a documented choice. Log which binary ran and its
  version.
- **Publish from CI with identity-based credentials rather than a stored token**:
  Microsoft Entra ID for the Marketplace (`vsce publish --azure-credential`) and
  trusted publishing for Open VSX (`ovsx publish --trusted-publishing`, with the
  workflow granted `id-token: write`). Check each CLI's `publish --help` and the
  registry's docs before writing the workflow; a personal access token is the
  fallback, not the default.
- **Mark previews with `--pre-release`**, not a SemVer suffix. Marketplace versions are
  `major.minor.patch`, and a pre-release and a stable upload need distinct versions.
