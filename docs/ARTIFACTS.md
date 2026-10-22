# Pinned artifacts

Download proprietary inputs only from the official Lenovo distribution. Do not upload installers, DLLs, keys, backups or fingerprint data to this repository.

| Input | SHA-256 |
|---|---|
| `74ti05afkkxbyyb0.exe` (Windows 10 reference installer) | `c94d7c866b0fc0be4d62511b780294900eef972f6e8ec9db761b74cfdf1af4ea` |
| `74ti04afkkxbyyb0.exe` (Windows 11 pairing encoder installer) | `27b211eee3f973b2e5b70823d6fb7c69394876839ab9e2e9a85f14b8ce1008ee` |
| Goodix `.610 Wbdi.dll` used by the pinned encoder | `567b5af3f2c51eca058172aaa0d0403d82680c75e77d2d073cfd403b1180fb8a` |

The Windows 10 `.520` DLL is a different artifact and is not substituted for the `.610` encoder. The installers are read/extracted as data. The encoder tests emulate only the pinned `SecWhiteEncrypt` function and its fixed helper hooks, not the complete Windows driver.

The C driver and its dependency revisions are recorded in `sources.lock.json`. Local Python changes are recorded in `patches/pairing-profile.patch` and the original/patched file hashes in `patches/pairing-profile.json`.
