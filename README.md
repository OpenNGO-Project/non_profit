## Non Profit

A maintained hard fork of the Frappe Non Profit app for Frappe v16 and ERPNext.
It includes provider-neutral recurring-gift reconciliation,
Household giving summaries, tribute-gift fulfillment state, membership, and
Swiss fundraising workflows.


### Installation

Using bench, [install ERPNext](https://github.com/frappe/bench#installation) as mentioned here.

Once ERPNext is installed, add non_profit app to your bench by running

```bash
bench get-app non_profit
```

After that, you can install non_profit app on required site by running

```bash
bench --site <site> install-app non_profit
```


### Documentation

Current fork documentation:

- `HOW_TO.md` - operator/admin workflows.
- `DOCUMENTATION.md` - technical architecture and app contracts.
- `REQUIREMENTS.md` - numbered behavior requirements.
- `AGENTS.md` - coding-agent rules and gotchas.


### License

GNU GPL V3
