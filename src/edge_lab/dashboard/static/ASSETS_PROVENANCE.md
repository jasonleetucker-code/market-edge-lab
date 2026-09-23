# Static asset provenance: dashboard fonts and icons

Every third-party asset in this directory, where it came from, and the hashes that let anyone
verify it. All assets are self-hosted. The dashboard makes no CDN or third-party requests.
Acquired 2026-09-23.

## Fonts: IBM Plex (SIL Open Font License 1.1, SPDX `OFL-1.1`)

Upstream repo: <https://github.com/IBM/plex>. The files are IBM's own **Latin1 "split" subsets**
(`fonts/split/woff2/*-Latin1.woff2`), used **byte-for-byte unmodified**, so the Reserved Font Name
"Plex" condition of the OFL is not triggered. They were taken from IBM's npm packages, which are
published from that repo. For each package, npm `gitHead` equals the commit that the release tag
dereferences to.

| Package (npm, latest stable) | Release tag in IBM/plex | Tag object | Commit (tag `^{}`) | npm tarball sha512 integrity |
|---|---|---|---|---|
| `@ibm/plex-sans@1.1.0` | `@ibm/plex-sans@1.1.0` | `036e2d2a727bd6a378f69b7cde8d8dd20c472dae` | `1da12f02587b630c07e92692d21492d722f53614` | `sha512-WPgvO6Yfj2w5YbhyAr1tv95RUz4LRJlqN+CmYvBglabXteufP1D1E9BABMde+ZIKdRbFJDoKF5eQzfhpnbgZcQ==` |
| `@ibm/plex-sans-condensed@2.0.0` | `@ibm/plex-sans-condensed@2.0.0` | `003d81ba2d9cfdd61ba39fdc60cc3dac44186a96` | `bb3ab6404e1881ea286f8742dc839e09057db6dd` | `sha512-dzgR4Npf/JJMiTYf6iOBQJpTDQfllZFLN0A0FkW5gtWhNr9JeQNvRrIRwJvbZHfL0I8wae8kIhO/ukYdeXW54g==` |
| `@ibm/plex-mono@2.5.0` | `@ibm/plex-mono@2.5.0` | `c71cbdbeb76cae994c88a81f391f97748280dd35` | `2f9ba1b25957d958db71a849e85d72e3ecfb845a` | `sha512-STBJIPxPomOYPmBMO7z5TKPJUotAF9u3gAUumTqVgwgrAO+K4FRNh0MlhsoJjKhJKsMbBJR10/bk4inkj/wc1w==` |

Each saved file was also checked against the repo itself. Its git blob id equals the blob at
`packages/<pkg>/<path>` on the pinned commit (GitHub contents API).

| File (`fonts/`) | Weight / style | Upstream path (in npm package; repo path is `packages/<pkg>/` + this) | Pinned commit | Bytes | SHA-256 |
|---|---|---|---|---|---|
| `plex-sans-400.woff2` | 400 normal | `plex-sans/fonts/split/woff2/IBMPlexSans-Regular-Latin1.woff2` | `1da12f02587b630c07e92692d21492d722f53614` | 20984 | `b5ad7bd39f996144915f0ad9849a90183b27d8c28ad97ed98af5b1bebc51f6b1` |
| `plex-sans-500.woff2` | 500 normal | `plex-sans/fonts/split/woff2/IBMPlexSans-Medium-Latin1.woff2` | `1da12f02587b630c07e92692d21492d722f53614` | 21960 | `b5610af04d0d4b5a14a621d96d974b993e945a065db1a8861918f69ef9321934` |
| `plex-sans-600.woff2` | 600 normal | `plex-sans/fonts/split/woff2/IBMPlexSans-SemiBold-Latin1.woff2` | `1da12f02587b630c07e92692d21492d722f53614` | 22260 | `fff0ab3a88b0b4aa0b693e4f0201359a15183b08e3fa5696d1918d8f0ade8ad5` |
| `plex-sans-condensed-600.woff2` | 600 normal | `plex-sans-condensed/fonts/split/woff2/IBMPlexSansCondensed-SemiBold-Latin1.woff2` | `bb3ab6404e1881ea286f8742dc839e09057db6dd` | 21988 | `6738b1096fd433204a070db0b4a9b1172ad3e6bdff8aad5f05f7351e7c157d06` |
| `plex-mono-400.woff2` | 400 normal | `plex-mono/fonts/split/woff2/IBMPlexMono-Regular-Latin1.woff2` | `2f9ba1b25957d958db71a849e85d72e3ecfb845a` | 17544 | `e8993d946649b9d01abb1ed06d574b19d8ea3e66b5c3948602db335c44c18e56` |
| `plex-mono-500.woff2` | 500 normal | `plex-mono/fonts/split/woff2/IBMPlexMono-Medium-Latin1.woff2` | `2f9ba1b25957d958db71a849e85d72e3ecfb845a` | 17868 | `41201b658a328b9d00368215c2f1102770f80b15952ab82631e4006255e6365d` |

**Total font bytes: 122,604 (119.7 KiB).**

### Glyph coverage (verified, not assumed)

Required code points: U+0020–007E, U+00A0, U+00A2 (¢), U+00B7 (·), U+00D7 (×), U+2013 (–),
U+2014 (—), U+2019 (’), U+2026 (…), U+2212 (−).

- IBM's shipped split CSS declares this `unicode-range` for every Latin1 file used:
  `U+0020-007E, U+00A0-00FF, U+0131, U+0152-0153, U+02C6, U+02DA, U+02DC, U+2013-2014,
  U+2018-201A, U+201C-201E, U+2020-2022, U+2026, U+2030, U+2039-203A, U+2044, U+20AC, U+2122,
  U+2212, U+FB01-FB02`. The Sans and Sans Condensed ranges also add U+0000 and U+000D.
- Each saved file was opened with fontTools 4.66.0 plus brotli, in a throwaway venv outside the
  project. Checks: the magic bytes are `wOF2`, the flavor is `woff2`, `OS/2.usWeightClass`
  matches the weight above, and `head.macStyle` is not italic. The best cmap contains
  **every** required code point, with 0 missing in all six files. The Sans and Condensed cmaps
  have 220 entries each and the Mono cmaps have 218.

The Latin1 subsets do not include Greek, Cyrillic, extended Latin or the "Pi" set, which holds
arrows, U+2032 prime, math symbols such as ≤ ≥ ≠ ≈, and U+2713 ✓. Text with those characters
falls back to the next font in the CSS stack.

### License file

`fonts/LICENSE-IBM-Plex-OFL.txt` is IBM Plex's `LICENSE.txt`, copied verbatim. The copies in all
three packages are identical. It has CRLF line endings upstream and keeps them here. It is 4456
bytes, SHA-256 `7e6b2818edbd8f6a01ae80641cc8f16a51080d08fb4e532be3a0b6f74adb07da`, and its git
blob id `c35c4c618fab33da8695177b3a6cefe0810b7b28` equals `packages/plex-sans/LICENSE.txt` at
`1da12f02587b630c07e92692d21492d722f53614`.

## Icons: Lucide (SPDX `ISC AND MIT`)

- Upstream repo: <https://github.com/lucide-icons/lucide>, latest release `1.47.0`, published
  2026-09-17. The tag is lightweight and points directly at commit
  `3b9ea6d08707edc439f25a4c354cb0d6b8bee973`.
- Source URL pattern:
  `https://raw.githubusercontent.com/lucide-icons/lucide/3b9ea6d08707edc439f25a4c354cb0d6b8bee973/icons/<name>.svg`
- `icons.svg` is **6783 bytes**, SHA-256
  `8fa9dc3245e8897540aff7902efdc8510035959a51fc91100c8db2e1cea74040`. It has LF line endings
  and is UTF-8.
- `LICENSE-Lucide.txt` is Lucide's `LICENSE` at the pinned commit, copied verbatim. It is
  3208 bytes, SHA-256 `b495047bd93a9b06913511076f504daba17d5bbeb3e0650f3bb53a4220329c57`, and
  its git blob id `718bb3f0e44153809972abed31839375804bf652` equals upstream. The file carries
  the ISC license and the **MIT license (Cole Bemis, Feather)** for the icons it lists as
  Feather-derived, so the effective licensing is ISC and MIT. The filename says ISC, but the
  file holds the full notice.

### How the sprite was built

The sprite contains one `<symbol id="i-<name>" viewBox="0 0 24 24">` per icon. Each symbol holds
only the icon's child shape elements, copied verbatim (whitespace between elements trimmed).
The upstream root attributes (`width`, `height`, `fill="none"`, `stroke="currentColor"`,
`stroke-width="2"`, `stroke-linecap/linejoin="round"`) are **dropped**. The dashboard CSS must
supply them.

The build asserted that every upstream root had exactly those standard attributes. It also
asserted that every child was a leaf shape element (path/circle/rect/line/polyline/polygon/
ellipse) whose only attributes were geometry. The output was re-parsed with
`xml.etree.ElementTree`, and the whole tree was checked against these allowlists:

- Elements: {svg, symbol, path, circle, rect, line, polyline, polygon, ellipse}
- Attributes: {xmlns, width, height, aria-hidden, focusable, id, viewBox, d, cx, cy, r, rx, ry,
  x, y, x1, y1, x2, y2, points}

The file contains no `style`, `xlink`, `href`, `script`, `<title>`, event attributes or
external references. The root is exactly
`<svg xmlns="http://www.w3.org/2000/svg" width="0" height="0" aria-hidden="true" focusable="false">`,
preceded by the provenance comment.

### Name mapping

- The requested `circle-help` does **not** exist at the pinned commit. Upstream
  `icons/circle-question-mark.json` lists `circle-help` and `help-circle` as deprecated aliases,
  so the symbol is `i-circle-question-mark`.
- All other requested names exist as canonical files at the pinned commit.
- `chart-candlestick` is canonical, with `candlestick-chart` as a deprecated alias.
  `briefcase-business` exists, so the requested name was used.

### Icons (37): upstream SVG SHA-256 at the pinned commit

`MIT` marks icons that are Feather-derived according to the list in Lucide's LICENSE, matched on
the name or an alias.

| Icon | Upstream `icons/<name>.svg` SHA-256 | Feather (MIT) |
|---|---|---|
| `layout-dashboard` | `281ab865b4c04dab32a04023473e448f58be6a7ad90769450ac3349d79dc4aed` | |
| `chart-candlestick` | `4cb3503f8b22d5b33237e05a6b7e0625e6d5669fef30827c6f8de42054e02432` | |
| `briefcase-business` | `98388a2bf7b9d102d77772d125d26f59ea3bed0d8573a5fc8907003099ae9a54` | |
| `target` | `96a6b16628825a1a207a77e9a5818f74c3e74ea3664783ff5c2a44e6347b90df` | MIT |
| `menu` | `af6491988ac1ba30dc5414f485bc48713e957e1edb0fbef4a0dd8691c3c21598` | |
| `shield` | `be32f6a86df7cbe43a83c439dd8849e5bcf5145e484d23420c20d8b98a78e82b` | |
| `flask-conical` | `a2ce857c159bef4c128a6d9f0b6dcbd6504ecf1a2a670ee220efd14fd032b561` | |
| `bell` | `394889e9631fe3a9a63be9a479a95b451b708e432d895978d21d9130b5ee5dbe` | |
| `chevron-left` | `83b0681aa38bf55e9d52a1e4b4cced624abe1fe7678ecafda133a574f1161d93` | MIT |
| `chevron-right` | `2758143d7b2434e4aa7307dfd34405c87909ff4052f21b5f3f40d45224b4f19b` | MIT |
| `chevron-down` | `66ea878e72ed3488bb3b464c39dfdccee8d1f78e560dccea40e5e12da0e87e87` | MIT |
| `search` | `283d371c2e433817bb9c0c8310caa6c77fa4177c0f4f1168d9c83b97af7389dc` | MIT |
| `x` | `4a9cdab38fbb96162e7dace28e33f4ca0e49d8963a6162abc3d4691b7d675117` | MIT |
| `circle-alert` | `ce3e98b7a03b78c0071131df42466e4e1ff5187fccad30e739ec9ce951cf685a` | MIT (alert-circle) |
| `triangle-alert` | `4866f38b8560d410f21e3226413e0b77997b6dfbb6931fadfe0a0d5aef9ffeb4` | MIT (alert-triangle) |
| `circle-check` | `9711e045a5999f8a3b0782eb88e09b04e0559bc7b379dcc0a4ae645223e10345` | |
| `circle-x` | `bcd8788901e6f29e1b231a81ba5e707d083d06cb4848a28f29407fab4f8e0b64` | MIT (x-circle) |
| `circle-question-mark` | `975db087da041530dbf59ba1e61a7b99c3519fad43dae6375e42ccc74ba63924` | MIT (help-circle) |
| `clock` | `e9d3e3acf4d1c280fcf8092293439dc0a4756a908ceb859de144b12451cd1cb9` | MIT |
| `info` | `bc977a64eb96f3e9c1041ffd09a3fceb70e3e65c02b571f76064062ed31f3cb9` | MIT |
| `external-link` | `3891241b8c3bfc3a8a930078f26ffc5a7e9763da6d0162ace2050b28d4c1d1fe` | MIT |
| `arrow-up-right` | `50b2503b9d11881142255466b7e3461d022b919735841c321d72003ac9959fe1` | MIT |
| `arrow-down-right` | `c3b557b5561c42008adfadade79341158dfd2cf3437b586fd0639447415f7545` | MIT |
| `minus` | `a0c743ab6dbf545d8a6e19ef3874f48ede686ce68d25e231bd81f540d97b1f19` | MIT |
| `lock` | `d2cfe60cac8deaef36442b5c8218c1e61abe18222784b2a370ea090d13fca840` | MIT |
| `database` | `471eb14bc8d144896a82dfc4aa9daf350f769f0896f4bef33e50aabdbb51130d` | MIT |
| `ban` | `2eba67f86d70bbd5d22e4211d44d7dda86c3397410f714765a12c3cd3ca0ebe3` | |
| `circle-dashed` | `9b964be491a821be8ffd714baf3b94ca2d70af789bddcfc1bda6bde250d89187` | |
| `arrow-left` | `c5f4b88076108eb1a0d95336e1aa7e7bb1419a3a92af96f6247d88cd3456f933` | MIT |
| `refresh-cw` | `2e10dd403c85a24f163d59fc6151aa21147fe9402e1305dfc8979208caee8944` | |
| `list-filter` | `36b94082bd7f161244c06a27cdeea647cb99ee5b805183cbeaf7ac3155a7103b` | |
| `cloud-sun` | `d3d0b5519e3e9e6073bc6d875fcb2b8d0a0c0d0062602490d444ef6a08bb2ab0` | |
| `trophy` | `c641553befdb899b2eb01075c0962c73b4b0e0d1835d9d407f5d5d4d70f77d03` | |
| `landmark` | `28408ef995796bffc390e8f217cdaa61e383627789d66300d4ff839248a3f144` | |
| `trending-up` | `c86a4afe20ceccd7a28e829a2cd83dbc40a8af51ffa9547332a9bac9a50a90ae` | |
| `layers` | `ce16d0a955e3581cda17f6b2fd5c5bc2034b405f9cecc31c8ebb8495b4afc1bb` | |
| `activity` | `050fbcda05e13c2051cf857683645e19c6b180861ef4d0cc28a6f09ba1ea1666` | |

## Line endings

`src/edge_lab/dashboard/static/.gitattributes` sets `* -text`, so git never converts line
endings in this directory and the hashes above hold on every checkout (the IBM Plex license
keeps its upstream CRLF bytes).

## Local edit after acquisition

The provenance comment at the top of `icons.svg` was changed from "(ISC License)" to name
both licenses (Lucide is ISC; Feather-derived icons are also MIT), and the license file was
named `LICENSE-Lucide.txt` instead of `LICENSE-Lucide-ISC.txt`. The symbols are unchanged.
The recorded `icons.svg` size and SHA-256 are for the edited file.
