# Attribution and licensing

This repository provides Ubuntu integration tooling and a local Python pairing patch. It fetches the upstream C driver and libfprint at pinned commits; their full source trees and proprietary Windows binaries are not included here.

| Component | Upstream / provenance | License |
|---|---|---|
| Goodix 5503 driver and Python pairing implementation | [Duro02/goodix-5503-linux](https://github.com/Duro02/goodix-5503-linux), commit `c7c22acb8ef6288742d53c381d2911858934cfe0` | LGPL-2.1-or-later |
| libfprint framework | [libfprint](https://gitlab.freedesktop.org/libfprint/libfprint), commit `80a4b5ec612892c5c056c48dddaa561452cf37ec` | LGPL-2.1-or-later |
| SIGFM matcher and libfprint patch | Included by the Goodix upstream, with its original contributor notices retained | LGPL-2.1-or-later |
| Ubuntu tooling, local pairing changes and project tests | This repository | LGPL-2.1-or-later |
| Artifact-specific Inno extractor | Altered Python implementation based on format/filter work from [Daniel Scharrer's innoextract](https://github.com/dscharrer/innoextract) | zlib-style license, full notice retained in `tools/extract_inno_payload.py` |
| Lenovo / Goodix Windows installers and DLLs | Downloaded by the user from Lenovo's official distribution; hashes are pinned | Proprietary; **not redistributed** |

The local pairing patch is identified as modified work and records original and patched file hashes. Upstream copyright and license notices must be retained. See [LICENSE](LICENSE) for LGPL 2.1; the code is offered under LGPL-2.1-or-later except for the extractor's retained license.

There is no claim of endorsement by Lenovo, Goodix, the libfprint maintainers, or the upstream driver authors. This project has not undergone an independent security review.
