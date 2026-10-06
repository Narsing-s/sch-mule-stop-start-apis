# API Group Configuration

Add the exact CloudHub 2.0 application names to the matching file:

- `config/eapi/apis.txt` — Experience APIs
- `config/papi/apis.txt` — Process APIs
- `config/sapi/apis.txt` — System APIs

You can paste comma-separated names:

```text
customer-eapi,order-eapi,payment-eapi
```

or one name per line:

```text
customer-eapi
order-eapi
payment-eapi
```

Comments beginning with `#` and blank lines are ignored. Names are de-duplicated.

Only the applications listed in these three files are controlled. Do not use an unrestricted ALL mode in this scheduler.
