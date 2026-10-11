NMU Wrestler Image Builder
==========================

This is a one-click GitHub Actions builder for the current 75-wrestler NMU roster.

What it does
------------
- Reads wrestler IDs/names from the supplied manifest.
- Searches Wikimedia Commons first.
- Strongly prefers 1998-2001 wrestling imagery when metadata/file names support it.
- Falls back to the wrestler's English Wikipedia lead image.
- Removes backgrounds in GitHub's cloud runner with rembg.
- Normalizes every asset to 800x1000 transparent PNG.
- Saves exactly: wrestlers/wrestler-ID.png
- Writes wrestlers/SOURCES.csv with source/license metadata.
- Never downloads from or hotlinks SmackDown Hotel.

How to use
----------
Upload the package contents to the root of the public nmu-assets repo, preserving folders.
Then go to Actions > Build NMU Wrestler Images > Run workflow.

The Action generates and commits the PNG files directly into wrestlers/.
Open wrestlers/MISSING.txt afterward. If it says 'No missing wrestler images.', all 75 were found.
If a few placeholders remain, only those IDs need manual replacement.
