# Assumed adjacent vertiport parking

User-confirmed modelling assumption: each active vertiport has adjacent parking. No search for separate real-world parking facilities is required.

The current AamMultimodalRoutingModule represents this as co-located parking at the vertiport road link, connected to the air link by an explicit walk leg with zero distance and zero travel time. This is an idealized transfer, not a measured pedestrian route. It satisfies the 1,000-metre and 1,200-second walking limits by construction. No additional parking capacity or parking tariff is introduced by this assumption.

Private-car access follows the road network to that location. A paired private-car tour must return to the same parking vertiport before retrieving the car. The 30-mile feeder catchment describes travel to the vertiport, not a permitted parking-to-terminal walking distance. Car-at-home alternatives leave the car at home and use non-private feeders.

This assumption is already represented by the running package: no binary, configuration, or running output was changed. Existing link-based parking charges remain governed by the inherited parking-cost handler; this assumption does not establish a calibrated vertiport parking price.

A positive terminal walk time or distance would require an explicit additional assumption and consistent changes to route timing, feasibility and scoring. None is silently added here.
