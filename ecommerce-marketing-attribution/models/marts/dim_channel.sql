-- Channel dimension with the paid / owned / earned split used in every mart.
select
    c.channel,
    c.channel_group,
    c.is_paid,
    c.sort_order
from (
    values
    ('paid_search_brand', 'paid', true, 1),
    ('paid_search_generic', 'paid', true, 2),
    ('paid_social', 'paid', true, 3),
    ('display', 'paid', true, 4),
    ('affiliate', 'paid', true, 5),
    ('email', 'owned', false, 6),
    ('organic_search', 'earned', false, 7),
    ('referral', 'earned', false, 8),
    ('direct', 'earned', false, 9),
    ('other', 'earned', false, 10)
) as c (channel, channel_group, is_paid, sort_order)
