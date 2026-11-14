# Third-party materials

The [MIT license](LICENSE) covers this project's original code, documentation,
tests and project-owned design assets. It does not change the licenses or other
terms of dependencies, research papers, paper excerpts, datasets, provider data,
or other third-party material referenced or processed by the application.
Retain upstream copyright and license notices when redistributing those materials.

## Dependencies

Python dependencies are declared in `pyproject.toml` and pinned in
`requirements.lock`; frontend dependencies and their published license metadata
are in `web/package.json` and `web/package-lock.json`. Dependencies are installed
separately and retain their own licenses. This repository's MIT declaration is
not a claim that every dependency is MIT-licensed.

In particular, the PDF extractor uses **PyMuPDF**, whose installed 1.28.2
distribution declares a choice of GNU AGPL 3.0 or an Artifex commercial license.
See the [upstream license documentation](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright)
and the license files in the installed distribution. The project's MIT license
does not waive those terms or establish a commercial license. An application
distributed or operated with PyMuPDF must satisfy the applicable upstream terms;
do not describe the complete dependency stack as MIT-only.

## Papers and data

Downloaded PDFs, extracted paper text, market data and disclosure datasets remain
subject to their source terms. Permission to download or use a source does not
grant the project permission to relicense it. Local `papers/` and `data/`
artifacts stay excluded from Git. Source URLs and provenance remain in the
project's audit reports and metadata.
