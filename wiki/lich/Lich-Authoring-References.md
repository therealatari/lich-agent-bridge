# Lich authoring references

Use these sources when a LAB script calls Lich APIs, consumes XML state, manages
containers, or changes a community script. Read the implementation before
inventing a replacement runtime contract.

## Source order

1. [Current Lich source](https://github.com/elanthia-online/lich-5).
2. [Lich YARD documentation](https://elanthia-online.github.io/lich-5-docs/)
   and its [source repository](https://github.com/elanthia-online/lich-5-docs).
3. [Lich DeepWiki](https://deepwiki.com/elanthia-online/lich-5) for architectural navigation.
4. Maintained community script source for integration examples.
5. A concrete failing trace or deterministic replay for a claimed defect.

Generated documentation is navigation, not stronger evidence than the code.
A repeated pattern across scripts does not establish a runtime bug.

## Local checkouts

Clone the upstream repositories into a directory chosen by the contributor.
For example, from a development directory:

```sh
git clone https://github.com/elanthia-online/lich-5.git
git clone https://github.com/elanthia-online/lich-5-docs.git
git -C lich-5 rev-parse HEAD
git -C lich-5-docs rev-parse HEAD
```

Record the revisions used in an investigation. DeepWiki is a website over the
Lich repository, not another repository to clone. Updating any checkout is a
separate deliberate action; preserve unrelated local changes.

## Runtime differences

A `.lic` script executes inside Lich with supplied globals such as Script,
GameObj, Room, XMLData, hooks, and command helpers. Lich also loads Ruby class
extensions during boot.

At inspected Lich revision
`4ed650ba9dab59bb524609986267302e219c651b`, NilClass's missing-method handling
can make an expression return nil where ordinary Ruby would raise. Before
calling a path impossible or reporting a Ruby exception, inspect
`lib/common/class_exts/` and the boot sequence at the actual target revision.

A standalone test harness should model only the runtime behavior relevant to
its assertion. Passing or failing ordinary Ruby tests alone does not establish
what the installed Lich runtime does.

## Change gate

1. Identify the exact API and read its implementation and focused tests.
2. Reproduce the failure with a sanitized trace or deterministic fixture.
3. Explain why existing state/refresh semantics do not already satisfy the call.
4. Test the original failure, not merely that a proposed workaround executes.
5. Prefer configuration or a narrow source repair over blanket rescanning.
6. Record source revision, upstream issue/PR where relevant, and verification limits.

Keep frontend-specific framing in an explicit presentation adapter.
Preserve attribution and verify licensing before redistributing external code.
