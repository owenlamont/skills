---
name: typescript
description: Write and review TypeScript to this project's standards — tsconfig flags and module settings, types, errors and promises, modules and packages, Biome and type-aware linting, running beside a native compiler with no API, and tests with Vitest or vscode-test. Use when authoring or reviewing TypeScript or a VS Code extension, changing a tsconfig, biome.json, .oxlintrc.json or .vscode-test file, choosing compiler or module settings, adding a lint rule or a tool that imports typescript, bundling, publishing a package, or writing and mocking TypeScript tests.
---

# TypeScript

Standards for writing TypeScript in this project. `software-engineering` carries the
language-neutral half and `docs` decides whether a comment is warranted; this skill is
what those leave to TypeScript. For a VS Code extension, also read
[references/vscode-extension.md](references/vscode-extension.md).

## Read the toolchain before writing against it

- **Read the project's `typescript` version, its Node floor (`engines.node`) and its
  `package.json` `type` before choosing syntax, flags or tools.** Node runs `.ts` files
  directly by stripping types, but only on recent lines and only for erasable syntax.
  Compiler defaults have also moved between majors, so a config that relies on them
  changes meaning on upgrade.
- **Before adding a tool, check whether it imports the `typescript` package's
  JavaScript API** — linters with type information, declaration bundlers,
  type-test runners. The native (Go) compiler ships `tsc` without that API, and a tool
  that needs it either refuses to install against it (a `typescript` peer range below
  the native major) or throws at startup. Check the tool's peer range and release notes
  rather than assuming either way.
- **Where such a tool must run beside the native compiler, alias the compatibility
  package TypeScript publishes for the last JavaScript-API major under the
  `typescript` name**, and install the native compiler under another. Check the
  TypeScript release notes for the package's current name; for the 6-to-7 transition
  it was:

  ```json
  "typescript": "npm:@typescript/typescript6@^6",
  "@typescript/native": "npm:typescript@^7"
  ```

  `node_modules/.bin/tsc` is then the native compiler and the alias carries its own
  `tsc6`; API consumers resolve `typescript` and get the one they support. Run the
  type-check gate with `tsc`. Drop the alias once every consumer supports the native API.

## Compiler configuration

**Model what actually loads the code.** One tsconfig cannot serve every runtime, and
TypeScript only checks what its `module` setting describes.

| Code is run by | `module` / `moduleResolution` | `verbatimModuleSyntax` |
| --- | --- | --- |
| Node, from emitted JS or `.ts` directly | `nodenext` | on |
| a bundler that emits ESM | `preserve` (or `esnext` + `bundler`) | on |
| a bundler that emits CommonJS | `commonjs` + `bundler` | off |

- **Match `module` to the module kind of the output, not the source syntax.** Modelling
  a CommonJS bundle as `esnext` lets ESM-only syntax through the type-check: `tsc`
  accepts `import.meta` and top-level `await`, and esbuild then only warns on
  `import.meta` and emits it empty. `module: commonjs` rejects both.
- **`verbatimModuleSyntax` is on wherever TypeScript classifies the source file as
  ESM** and off where it classifies it as CommonJS, where it rejects every `import` and
  `export` (TS1295, TS1287). Under `nodenext` the nearest `package.json` `type` decides
  the classification of a `.ts` file, so set `"type": "module"` or the flag fails every
  file. Where it is off, Biome's `useImportType` keeps type-only imports marked.
- **Never `moduleResolution: node` / `node10`** — deprecated, then removed by the native
  compiler.
- **Set `strict` explicitly** even where it is the default, and never weaken it or a
  sub-flag to make an error go away.
- **Set `isolatedModules` whenever anything other than `tsc` turns TS into JS** —
  esbuild, Vitest, Node's type stripping. Each compiles one file at a time and cannot
  see the types that file imports.
- **Set `types` explicitly** to the ambient packages the code uses (`["node"]`, plus a
  test runner's globals if it injects them). Recent compilers default it to empty, so
  an implicit `process` or `describe` silently stops type-checking on upgrade.
- **New projects also set `noImplicitOverride`, `noUncheckedIndexedAccess` and
  `erasableSyntaxOnly`.** In an existing project, leave its setting for each: adopting
  one is its own change, sized by the errors it raises, and some well-maintained
  projects turn `noUncheckedIndexedAccess` off on purpose.
  - `erasableSyntaxOnly` rejects at type-check the syntax Node's type stripping
    rejects at run time. Skip it only for a library that emits CommonJS and needs
    `export =`.
  - `exactOptionalPropertyTypes` is the project's call: it often fails against a
    dependency's own types rather than yours.
- **Run `tsc --noEmit` (or `tsc -b`) as its own CI gate.** A bundler, test runner or
  Node's type stripping succeeding proves the syntax parses, not that it type-checks.

## Types

- **No new `any`.** Type an untrusted value — parsed JSON, a caught error, a message
  from another process — as `unknown` and narrow it. Where interop forces `any`, keep it
  to one line with a comment naming the reason. Don't escalate a repo's `noExplicitAny`
  setting; the rule governs what you write.
- **Narrow rather than cast.** `as T` and `!` emit no runtime check, so prefer a type
  guard, an `in` / `typeof` / `instanceof` check, or validation. Where a cast is right,
  the invariant that makes it safe belongs in a comment beside it. `as unknown as T` is
  a review finding unless it works around a demonstrably wrong third-party type.
- **Validate at the boundary, never assert.** Types are erased, so data from the
  network, disk, environment or another process needs a runtime schema that also
  produces the type. Use the project's validation library.
- **No new `enum`, `const enum`, runtime `namespace`, parameter property or
  `import x = ...` alias**, flag or no flag. Each needs code generation, so Node cannot
  strip it. Use a string-literal union for a closed set of values, and an `as const`
  object plus a derived union where the values exist at runtime:

  ```ts
  export const Level = { Low: "low", High: "high" } as const;
  export type Level = (typeof Level)[keyof typeof Level];
  ```

  Ambient `declare namespace` blocks are type-only and stay allowed.
- **Use `satisfies` to check a literal against a type without widening it**; annotate
  instead when you want the wider type.
- **Model alternatives as a discriminated union, not one object of optional fields,
  and close every `switch` over one with a `never` check** so a new variant fails to
  compile:

  ```ts
  default:
    return assertNever(shape); // function assertNever(x: never): never { throw ... }
  ```

- **`@ts-expect-error` with a reason, never `@ts-ignore`.** The former fails once the
  error it hides is gone; the latter hides whatever error appears next.

## Errors and promises

- **Throw only `Error` instances**, and catch as `unknown` (`strict` types it so).
  Narrow with `instanceof` before reading properties.
- **Add context by wrapping with `new Error(message, { cause })`**, never by
  concatenating the old message and dropping the original.
- **Subclass `Error` only where a caller branches on the type**, and set `name`. Give
  callers a stable `code` field rather than asking them to match message text.
- **Every promise is awaited, returned, or given a rejection handler.** `void` marks a
  deliberate fire-and-forget only once a `.catch` is attached: `void p` alone discards
  the rejection exactly like a bare `p;`.
- **Don't pass an async function where the callee expects a sync callback** —
  `forEach`, an event handler typed `() => void`, a void-returning property. The callee
  drops the promise and its rejection. Loop with `for … of` and `await`, or attach the
  handler inside.
- `return await` inside a `try` block, so the `catch` sees the rejection.

## Modules and packages

- **Named exports.** Use a default export only where a framework requires one.
- **No barrel files inside an application.** Import from the defining module. A
  published package has one entry module per public entry point, and nothing else
  re-exports.
- **A new published library is ESM only** (`"type": "module"`); a bundled application
  or extension emits whatever its host loads. Add a CommonJS build for a named
  consumer that cannot load ESM, never "just in case": dual packages carry two copies
  of every module and the hazards that brings.
- **A published package declares `exports`, with the `types` condition first and
  `default` last** — conditions match in key order.
- **A library emits with `tsc`, unbundled,** unless bundling solves a named problem;
  an application or extension bundles. Check that a bundler is still maintained before
  adopting it.
- **Check the packed artefact, not the source tree.** Before releasing a library, run
  `publint` and `@arethetypeswrong/cli` against `npm pack` output (or the repo's
  equivalent check). A broken `exports` map or missing declarations pass every source
  test.
- **Keep the repo's package manager.** Whatever it is: commit the lockfile, install
  frozen in CI (`npm ci`, `pnpm install --frozen-lockfile`), and approve install scripts
  per package rather than allowing them all.

## Lint and format

- **An existing project keeps its linter and formatter.** Don't introduce a second
  formatter over the same files, and don't swap a working linter for a preferred one.
- **A new project uses Biome for formatting and linting** with its recommended preset,
  plus `useThrowOnlyError`, which the preset leaves off.
- **Promise rules need a type-aware linter that reads declaration files, and Biome's
  own type rules don't.** Biome's nursery promise rules infer types from project source.
  On a canary of floating calls into `@types/node` and `@types/vscode` they reported
  none of four, where oxlint and typescript-eslint caught all four once
  `checkThenables` was on. Re-run the canary
  before relying on a newer Biome for this. No domain or group switch enables these
  nursery rules: each must be named.
- **Beside Biome, add oxlint in type-aware mode, narrowed to the type-aware rules** so
  the two never report the same thing. oxlint ships its own type checker, so it needs no
  `typescript` API:

  ```json
  {
    "categories": { "correctness": "off" },
    "rules": {
      "typescript/no-floating-promises": [
        "error",
        { "ignoreVoid": false, "checkThenables": true }
      ],
      "typescript/no-misused-promises": "error",
      "typescript/await-thenable": "error"
    }
  }
  ```

  Install `oxlint` and `oxlint-tsgolint`, and run `oxlint --type-aware`. Without the
  flag oxlint skips every typed rule and still exits 0, so check that the CI and hook
  commands carry it. `ignoreVoid: false` is what enforces the `void`-needs-a-handler
  rule above; the default accepts a bare `void p`. `checkThenables` extends the rule to
  non-`Promise` thenables, which some APIs return.
- **A project on ESLint uses typescript-eslint's type-checked config with
  `projectService`.** Where its `typescript` peer range excludes the installed
  compiler, use the alias recipe under *Read the toolchain*. Don't downgrade the
  compiler for it.

## Testing

- **Vitest for TypeScript that does not need a host to run**; `node:test` for a Node
  package that must stay dependency-free. `node:test` module mocking and coverage have
  been experimental, so check their status before relying on them. Code that needs the
  VS Code API runs in the real extension host (see the reference).
- **Run tests in terminating mode — `vitest run`, never bare `vitest` or a watch
  script.** Watch mode never exits.
- **A passing suite is not a type-check.** Vitest and Node's type stripping drop types
  without checking them. Keep `tsc --noEmit` a separate gate. Put type-level assertions
  (`expectTypeOf`) for a library's generic API in `*.test-d.ts` under
  `vitest --typecheck`, which drives the project's own `tsc`. A type-test tool built on
  the `typescript` API checks with the API compiler, not the native one, so its pass
  says nothing about the native compiler; `tsc` stays the gate.
- **Prefer, in order: the real dependency, a fake passed in through the public
  boundary, a spy on a real object, a network-level mock, a module mock.** Each step
  right needs a stronger reason. Mock the process, filesystem and network edges, not the
  code's own modules. Set `restoreMocks: true` so spies don't leak between tests.
- **No retries on unit or integration tests.** A test that passes on retry is flaky,
  and a retry hides it.
- **Snapshots are small enough to review.** Never update snapshots wholesale to make a
  failing run pass: an updated snapshot is a behaviour change and its diff needs reading.
- **Coverage: collect it, never lower an existing gate, and don't invent a percentage.**
  Well-maintained TypeScript projects collect coverage, and some fail CI on a drop, but
  they rarely enforce a fixed threshold. Use the V8 provider, and set `coverage.include`
  so untested files count as uncovered rather than vanishing from the report.
