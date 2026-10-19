Testimonials — one JSON file per client quote.

NOTHING here is rendered until you add a file, and the homepage testimonial
section is hidden entirely while this folder is empty. That is deliberate: an
invented testimonial is the single most damaging thing that could go on this
site.

Add one file per quote, e.g. testimonials/acme-offsite.json:

{
  "order": 1,
  "quote": "What they actually said, in their words.",
  "name": "Full name",
  "role": "Their job title",
  "organisation": "Their company",
  "photo": "/static/images/testimonials/their-photo.jpg"
}

Get written permission to use the name, role and organisation before adding it.
`photo` is optional; `quote`, `name` and `organisation` are required.
