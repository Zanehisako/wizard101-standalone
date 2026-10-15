# Included software and corresponding sources

Original launcher, build scripts and synthetic tests: MIT (Project-MIT.txt).
Twofish 0.3 by Niels Ferguson: original permissive notice (Twofish-notice.txt).
D9VK and renderer changes: upstream zlib/libpng license (D9VK/).
Wine 11.0 from CodeWeavers 26.3.0: LGPL 2.1 or later; bundled sublibraries
retain their individual notices (Wine/). This includes FAudio and vkd3d.
MoltenVK and its SPIRV-Cross: Apache 2.0 and component notices (MoltenVK/).
GMP: LGPL 3 or GPL 2 or later (GMP/). Nettle: LGPL 3 or GPL 2 or later
(Nettle/). GnuTLS: LGPL 2.1 or later for the library, with individual component
notices (GnuTLS/). FreeType: the FreeType License (FreeType/docs/FTL.TXT.txt).
Portions of this software are copyright (c) 2024 The FreeType Project
(www.freetype.org). All rights reserved.
The MinGW-w64 runtime retains its ZPL and component terms; GCC runtime
libraries use GPL 3 with the GCC Runtime Library Exception 3.1. Their notices
are included alongside the project notices.

See the original notices for exact terms and copyright holders. All runtime
and renderer source inputs, including component notices, are shipped in
Wizard101-Native-dependency-sources.tar.gz; hashes are in sources.lock.json.
Wizard101-Native-source.tar.gz contains the clean project, patches, configure
options and one-command build/relink scripts. Extract its repository and put
the dependency archives in cache/ (or allow the builder to fetch those same
checksum-pinned archives). Run python3 build.py. W101_RUNTIME_ROOT selects a
replacement runtime; alternatively replace and ad-hoc sign a modified app.

Apple system libraries, macOS, Rosetta and KingsIsle game files are supplied
by their owners and are not included in these dependency source archives.
