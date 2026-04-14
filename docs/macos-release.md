# macOS Distribution Release

The desktop packaging pipeline supports two release modes:

- local packaging: produces an unsigned or locally signed app bundle and DMG for internal verification
- distribution packaging: requires a valid `Developer ID Application` signing identity plus Apple notarization credentials

## Recommended Release Flow

```bash
npm install --ignore-scripts
npm run desktop:release:prepare
npm run desktop:release:preflight
npm run desktop:package
```

For an external macOS release, use the stricter distribution gate:

```bash
npm run desktop:release:preflight:distribution
npm run desktop:package:distribution
```

## Signing Requirements

`desktop:package:distribution` expects one of these signing setups:

- a locally installed `Developer ID Application` certificate in the macOS keychain
- or `CSC_LINK` plus `CSC_KEY_PASSWORD` so `electron-builder` can import the signing certificate at build time

If `CSC_NAME` is set, it must match an installed `Developer ID Application` identity.

## Notarization Requirements

`electron-builder` will notarize automatically when one of these credential groups is present:

1. Recommended API key flow

- `APPLE_API_KEY`
- `APPLE_API_KEY_ID`
- `APPLE_API_ISSUER`

2. Apple ID flow

- `APPLE_ID`
- `APPLE_APP_SPECIFIC_PASSWORD`
- `APPLE_TEAM_ID`

3. Keychain profile flow

- `APPLE_KEYCHAIN_PROFILE`
- optional `APPLE_KEYCHAIN`

## Current macOS Build Settings

The desktop builder is configured with:

- `hardenedRuntime: true`
- explicit mac entitlements files under [apps/desktop/build](/Users/didi/AgentProjects/recurit-agent/apps/desktop/build)
- `notarize: true`
- `dmg.sign: false`

The preflight script reports whether the current machine is ready for distribution release and which notarization mode is active.
