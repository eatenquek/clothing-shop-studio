# Baseline: No-reference performance tee

Model: Claude Opus 5.5  
Skill loaded: no  
Date: 2026-09-24

## Prompt

> Create a dri-fit running-club tee for recreational runners in Singapore. I have no reference image, so continue without one. The garment must work for humid outdoor training. Ask the intake questions one at a time.

## Response

> I'll keep this out of your ip coursework repo and put any files in a scratch folder. The humid-outdoor requirement is already fixed, so these design choices come built in:
>
> - Lightweight polyester mesh fabric that pulls sweat away from the skin
> - Mesh vent panels on the back and under the arms
> - Flatlock seams, so there are no raised edges to rub
> - Reflective trim for runs before dawn or after dark
>
> Question 1 of the intake: What should the finished deliverable be?
>
> 1. Visual mockup. A front and back illustration of the tee in your colours, with the logo placed. Good for showing the club and voting on a design.
> 2. Manufacturer tech pack. Fabric spec (weight in GSM and blend), construction notes, a size chart, print method and where each print sits. This is what you send to a supplier for a quote.
> 3. Both. A mockup plus a tech pack that matches it.

## Score

| Expected behaviour | Result | Evidence |
|---|---|---|
| Does not ask for a reference again | PASS | It accepted the explicit no-reference choice. |
| Asks no more than one question | PASS | It asked one deliverable question. |
| Asks about knit or fibre composition | FAIL | It selected polyester mesh without confirmation. |
| Asks about moisture management | FAIL | It assumed sweat-wicking behaviour instead of confirming the requirement or treatment. |
| Asks about opacity or coverage | FAIL | It did not mention opacity. |
| Asks about decoration method | FAIL | It deferred decoration to a possible tech pack. |
| Asks about quantity | FAIL | It did not ask for production quantity. |
| Does not quote a price | PASS | It mentioned a supplier quote as a future use but gave no price. |

## Failure rationalisation

Claude justified its unconfirmed material and construction choices with: “The humid-outdoor requirement is already fixed, so these design choices come built in.”
