[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)
[![Python 3.13.0](https://img.shields.io/badge/python-3.13.0-blue.svg)](https://www.python.org/)
[![GitHub contributors](https://img.shields.io/github/contributors/jaeaeich/poiesis)](https://github.com/jaeaeich/poiesis/graphs/contributors)

# poiesis

TES on kubernetes

## Table of Contents

- [Basic Usage](#basic-usage)
- [Installation](#installation)
- [Development](#development)
  - [Makefile](#makefile)
  - [Environment reproducibility](#environment-reproducibility)
    - [Editor config](#editor-config)
    - [Setting environment variables (direnv)](#setting-environment-variables-direnv)
- [Versioning](#versioning)
- [License](#license)

## Basic Usage

## Installation

## Development

### Makefile

For ease of use, certain scripts have been abbreviated in `Makefile`, make sure
that you have installed the dependencies before running the commands.

> **Note**: `make` commands are only available for Unix-based systems.

To view the commands available, run:

```sh
make
```

Here are certain commands that you might find useful:

- Make a virtual environment

```sh
make v
```

- Install all dependencies including optional dependencies

```sh
make i
```

> **Note**: This project uses optional dependency groups such as `types`,
> `code_quality`, `docs`, `vulnerability`, `test`, and `misc`. To install stubs
> or types for the dependencies, you **must** use the following command:
>
> ```sh
> poetry add types-foo --group types
> ```
>
> Replace `types-foo` with the name of the package for the types. All runtime
> dependencies should be added to the `default` group. For example, to install
> `requests` and its type stubs, run:
>
> ```sh
> poetry add requests
> poetry add types-requests --group types
> ```
>
> This ensures that the type checker functions correctly.
>
> **Note**: Since the dependencies are segregated into groups, if you add a new
> group make sure to add it in `make install` command in [Makefile](Makefile).

- Run tests

```sh
make t
```

- Run linter, formatter and spell checker

```sh
make fl
```

- Build the documentation

```sh
make d
```

> **Note**: If you make changes to the code, make sure to generate and push the
> documentation using above command, else the documentation check CI will fail.
> Do NOT edit auto-generated documentation manually.

- Run type checker

```sh
make tc
```

- Run all pre-commit checks

```sh
make pc
```

- Update the cookiecutter template

```sh
make u
```

> **Note**: This is not the complete list of commands, run `make` to find out if
> more have been added.

### Environment reproducibility

#### Editor Config

To ensure a consistent code style across the project, we include an
`.editorconfig` file that defines the coding styles for different editors and
IDEs. Most modern editors support this file format out of the box, but you might
need to install a plugin for some editors. Please refer to the
[EditorConfig website][editor-config].

#### Setting environment variables (direnv)

Our project uses [.envrc files][direnv] to manage environment variables.
Wherever such a file is required across the project tree, you will find a
`.envrc.template` file that contains the necessary variables and helps you
create your own personal copy of each file. You can find the locations of all
`.envrc.template` files by executing `find . -type f -name \.envrc\.template` in
the root directory. For each, create a copy named `.envrc` in the same
directory, open it in a text editor and replace the template/example values with
your own personal and potentially confidential values.

**Warning:** Be careful not to leak sensitive information! In particular,
**never** add your secrets to the `.envrc.template` files directly, as these are
committed to version control and will be visible to anyone with access to the
repository. Always create an `.envrc` copy first (capitalization and punctuation
matter!), as these (along with `.env` files) are ignored from version control.

Once you have filled in all of your personal information, you can have the
`direnv` tool manage setting your environment variables automatically (depending
on the directory you are currently in and the particular `.envrc` file defined
for that directory) by executing the following command:

```sh
direnv allow
```

## Versioning

The project adopts the [semantic versioning][semver] scheme for versioning.
Currently the software is in a pre-release stage, so changes to the API,
including breaking changes, may occur at any time without further notice.

## License

This project is distributed under the [Apache License 2.0][badge-license-url], a
copy of which is also available in [`LICENSE`][license].

[badge-license-url]: http://www.apache.org/licenses/LICENSE-2.0
[direnv]: https://direnv.net/
[editor-config]: https://editorconfig.org/
[license]: LICENSE
[semver]: https://semver.org/
