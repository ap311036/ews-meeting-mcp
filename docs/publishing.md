# Publishing

This project publishes the npm wrapper and Python source files as the `ews-meeting-mcp` package.

## Manual Checklist

```bash
npm pack --dry-run
npm login
npm publish --access public
```

For internal company use, prefer a scoped name or a private registry, for example `@your-org/ews-meeting-mcp`.

## GitHub Actions Release Flow

1. Create an npm automation token with publish access.
2. Add it to the GitHub repository secrets as `NPM_TOKEN`.
3. Bump `package.json` version locally.
4. Commit and push to `master`.
5. Create and push a matching tag, for example:

```bash
git tag v0.1.18
git push origin master v0.1.18
```

The workflow validates Python tests, Node wrapper tests, and `npm pack --dry-run` before publishing.

It also checks that `vX.Y.Z` matches `package.json` version and skips publishing if that version already exists on npm.

You can also run the workflow manually from GitHub Actions. Manual runs validate by default; set `publish=true` to publish.
