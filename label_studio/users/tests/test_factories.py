import factory.random
from users.tests.factories import UserFactory


def test_user_factory_emails_remain_unique_when_faker_repeats():
    state = factory.random.get_random_state()
    try:
        factory.random.reseed_random(42)
        first = UserFactory.build()
        factory.random.reseed_random(42)
        second = UserFactory.build()
        assert first.email != second.email
    finally:
        factory.random.set_random_state(state)
