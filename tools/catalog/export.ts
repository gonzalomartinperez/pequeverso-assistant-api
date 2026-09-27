/**
 * Builds assistant/catalog.v1.json from a Pequeverso storefront source tree.
 *
 * Run by scripts/sync_catalog.py inside an isolated `git archive` of a pinned storefront commit
 * (never in a working tree). It reads the storefront's own typed registry and copy, so every fact
 * keeps the storefront as its source of truth. Post-purchase offers are excluded by design
 * (owner decision 2026-09-24: paid extras never appear before purchase); their names become
 * forbidden terms for the answer validator.
 *
 * Usage: node export.ts <site-origin> <revision> <generated-at-iso>
 */
import { guaranteeDays, hotmart, localCurrencyNote, formatUsd } from "./config/commerce.ts";
import { site } from "./config/site.ts";
import { consumerLaw } from "./content/es/legal/argentina.ts";
import { hotmartFacts } from "./content/es/legal/hotmart.ts";
import { seller } from "./content/es/legal/seller.ts";
import { soporteCopy } from "./content/es/soporte.ts";
import { graciasCopy } from "./content/es/gracias.ts";
import { getImage } from "./src/lib/media.ts";
import { coreProducts, offerProducts } from "./src/products/index.ts";

const [origin, revision, generatedAt] = process.argv.slice(2);
if (!origin || !revision || !generatedAt) throw new Error("usage: export.ts <origin> <revision> <generated-at>");
const abs = (path: string) => `${origin}${path}`;
const image = (id: string) => {
  const found = getImage(id);
  return { url: abs(found.src), width: found.width, height: found.height, alt: found.alt };
};

const products = coreProducts().map((product) => {
  const copy = product.copy;
  const pdp = copy.hero.pdp;
  return {
    id: product.slug,
    name: product.name,
    path: product.path,
    purchase_path: `${product.path}#comprar`,
    summary: product.seo.description,
    age_range: product.composition.ageRange,
    format: pdp?.details.format.text ?? copy.subtitle,
    usage: pdp?.details.usage.text ?? copy.hero.lead,
    pdf_count: product.composition.pdfCount,
    page_count: product.composition.pageCount,
    image: image(product.media.hero),
    price: {
      amount: product.pricing.list.toFixed(2),
      currency: "USD",
      display: formatUsd(product.pricing.list),
      note: localCurrencyNote,
      tax_note: copy.hero.taxNote,
    },
    resources: product.resources.map((resource, index) => ({
      id: resource.id,
      title: resource.title,
      pages: resource.pages,
      description: index === 0 ? `Material principal. ${resource.description}` : `Bono incluido. ${resource.description}`,
      image: image(resource.card),
    })),
    method: copy.method.steps.map((step) => `${step.title}: ${step.text}`),
    audience_for: copy.audience?.yes.items ?? [],
    audience_not_for: copy.audience?.no.items ?? [],
    age_guidance: (copy.hero.ages?.items ?? []).map((age) => ({ label: `${age.label} años`, hint: age.hint })),
  };
});

const faqDocuments = coreProducts().flatMap((product) =>
  product.copy.faq.items.map((item, index) => ({
    id: `faq.${product.slug}.${String(index + 1).padStart(2, "0")}`,
    kind: "faq",
    title: item.q,
    text: item.a,
    url: abs(`${product.path}#preguntas`),
  })),
);

const support = abs("/soporte/");
const purchases = abs("/compras-y-reembolsos/");
const documents = [
  ...faqDocuments,
  {
    id: "policy.guarantee",
    kind: "policy",
    title: "Garantía y reembolsos",
    text: `Tienes ${guaranteeDays} días desde la compra para pedir el reembolso a través de Hotmart, en refund.hotmart.com, con tu número de transacción (empieza con HP). El productor tiene hasta ${hotmartFacts.producerResponseDays} días para responder y la aprobación puede tardar hasta ${hotmartFacts.approvalDays} días. El dinero vuelve por el mismo medio de pago: ${hotmartFacts.refundTiming}.`,
    url: purchases,
  },
  {
    id: "policy.payment",
    kind: "policy",
    title: "Pago y moneda",
    text: `${localCurrencyNote} El pago se hace en la página segura de Hotmart, que es quien procesa el cobro; el cargo aparece a nombre de Hotmart. Pequeverso no ve ni guarda datos de pago.`,
    url: purchases,
  },
  {
    id: "policy.delivery",
    kind: "policy",
    title: "Entrega digital",
    text: "Es un producto digital, no se envía nada físico. Hotmart envía el acceso al correo usado en la compra cuando aprueba el pago; también se entra en consumer.hotmart.com con ese correo, en “Mis compras”. Con pagos no inmediatos (boleto, transferencia o efectivo) el acceso se libera cuando Hotmart confirma el pago.",
    url: support,
  },
  {
    id: "policy.withdrawal-ar",
    kind: "policy",
    title: "Botón de arrepentimiento (Argentina)",
    text: `Si compras desde Argentina, la ley de defensa del consumidor te permite revocar la compra dentro de ${consumerLaw.revocationDays} días corridos; la página de arrepentimiento explica cómo pedirlo y en otros países rigen tus propias normas.`,
    url: abs("/arrepentimiento/"),
  },
  ...soporteCopy.routes.map((route, index) => ({
    id: `support.route.${index + 1}`,
    kind: "support",
    title: route.title,
    text: route.text,
    url: support,
  })),
  {
    id: "support.limits",
    kind: "support",
    title: soporteCopy.limits.title,
    text: `${soporteCopy.limits.items.join(" ")} ${soporteCopy.limits.note}`,
    url: support,
  },
  {
    id: "support.contact",
    kind: "support",
    title: "Contacto",
    text: `Soporte por correo en ${seller.supportEmail}; respondemos normalmente en ${seller.responseTime}. Incluye el correo de la compra y el código de transacción HP si ya compraste.`,
    url: support,
  },
  ...graciasCopy.help.items
    .filter((item) => !/reembolso/i.test(item.title))
    .map((item, index) => ({
      id: `support.access.${index + 1}`,
      kind: "support",
      title: item.title,
      text: item.text,
      url: support,
    })),
];

const links = [
  { id: "support", label: "Soporte y contacto", url: support },
  { id: "purchases-refunds", label: "Compras y reembolsos", url: purchases },
  { id: "withdrawal", label: "Botón de arrepentimiento", url: abs("/arrepentimiento/") },
  { id: "hotmart-purchases", label: "Mis compras en Hotmart", url: hotmart.consumerArea },
  { id: "hotmart-refund", label: "Pedir reembolso en Hotmart", url: hotmartFacts.urls.refundForm },
  ...coreProducts().map((product) => ({
    id: `product-page.${product.slug}`,
    label: `Ver ${product.name}`,
    url: abs(product.path),
  })),
];

const catalog = {
  schema_version: 1,
  generated_at: generatedAt,
  source: { repository: "gonzalomartinperez/pequeverso", revision },
  site: {
    name: site.name,
    origin,
    language: "es",
    support_email: seller.supportEmail,
    support_link_id: "support",
  },
  products,
  documents,
  links,
  forbidden_terms: [
    ...offerProducts().flatMap((offer) => [offer.name, offer.shortName]),
    "Trazos y Sonidos",
  ],
};

process.stdout.write(`${JSON.stringify(catalog, null, 2)}\n`);
