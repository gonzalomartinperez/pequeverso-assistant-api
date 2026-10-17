# Software license and reserved material

The owner-authored software and its technical documentation are licensed under the
[MIT License](LICENSE), copyright © 2026 Gonzalo Martín Pérez. This covers the
application, tests, build and verification tooling, software configuration structure,
and first-party technical diagrams, except for embedded material described below.
The software permission does not transfer ownership of excluded content or grant
access to private services or data.

## Material outside the software license

The following material is not licensed under MIT by this repository:

- The Pequeverso name, logos, trademarks, product names and brand identity.
- Commercial products, teaching material, customer-facing copy, product descriptions,
  catalog payload content and source datasets, including `catalog/**` and business
  content embedded in examples, fixtures, responses or screenshots.
- Photographs, illustrations, video, product previews and other media, including the
  brand and product content visible in `docs/verification/**` screenshots.
- Customer, conversation, identity, order, operational and accounting data, evaluation
  responses, credentials or any other private data. A public fixture or example does
  not grant a license to an actual person's data.
- Third-party software, fonts, dependencies, base images, affiliate producer material
  and public source articles. Their respective authors retain their rights and their
  own licenses or publication terms continue to apply.

Pequeverso-owned brand and commercial material retain their existing reserved rights;
third-party material is not claimed as Pequeverso property. Public availability and
this software license do not grant permission to redistribute products or to present
another business using Pequeverso's identity. The storefront's
[content and media notice](https://github.com/gonzalomartinperez/pequeverso/blob/main/LICENSE-CONTENT.md)
and this repository's [catalog provenance](docs/catalog.md) document those boundaries.

## Third-party attribution and distribution

Dependencies are enumerated in `pyproject.toml` and the frozen `uv.lock`; their
individual license and copyright files remain authoritative. This notice does not
replace, remove or relicense any dependency notice. Container base layers retain
their distribution and Python notices. The application runtime includes this
repository's `LICENSE` and `NOTICE.md` at `/app/`; redistribution of the software must
preserve its MIT copyright and permission notice and any applicable third-party
notices. No claim of complete dependency-license clearance is made here.
