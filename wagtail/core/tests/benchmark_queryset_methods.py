import uuid

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from wagtail.core.models import Page
from wagtail.tests.benchmark import Benchmark
from wagtail.tests.testapp.models import (
    CustomRichBlockFieldPage, DefaultRichBlockFieldPage, DefaultStreamPage, StreamPage)


class PageQueryBenchmark(Benchmark):
    """
    A benchmark class that tests the performance of a query
    (returned by get_test_query()) with an increasing number of pages
    """

    # create pages of varying types for a more realistic test
    page_types = (
        CustomRichBlockFieldPage,
        DefaultStreamPage,
        DefaultRichBlockFieldPage,
        StreamPage,
    )
    # repeat each test with these numbers of pages
    create_count_steps = (5, 15, 75, 150)
    # test the query this number of times for each number of pages
    repeat = 15
    # used in printed output when set
    test_description = None
    # output
    output_all_measurements = False
    output_summary = True

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.home_page = Page.objects.get(depth=2)

        # helps with upcasting
        Page.get_concrete_subclass_related_names()
        for model in Page.get_concrete_subclasses():
            # helps defer_large_fields()
            model.large_field_names()
            # Load all content types into memory (by ID and model)
            # aid original and new implementations
            ct = ContentType.objects.get_for_model(model)
            ContentType.objects.get_for_id(ct.id)

    @classmethod
    def get_test_description(cls):
        return cls.test_description if cls.test_description is not None else cls

    def create_pages(self, number):
        stream_value = (
            "["
            + ",".join(['{"type": "text", "value": "%s"}' % ("foo" * 1000)] * 100)
            + "]"
        )
        number_per_type = number // len(self.page_types)
        remainder = number - number_per_type * len(self.page_types)

        for i, model in enumerate(self.page_types):
            if i == 0 and remainder:
                to_create = number_per_type + remainder
            else:
                to_create = number_per_type
            for num in range(to_create):
                unique_string = model.__name__.lower() + "-" + str(uuid.uuid4())
                self.home_page.add_child(
                    instance=model(
                        title=unique_string, slug=unique_string, body=stream_value
                    )
                )

    def test(self):
        existing = 0
        for num in self.create_count_steps:
            desc = f"{self.get_test_description()} ({num} pages)"
            print(f"\n\n{desc}")
            print("=" * len(desc))
            self.expected_result_length = num
            self.create_pages(num - existing)
            existing = num
            super().test()

    def bench(self):
        result = self.get_test_query()
        self.assertEqual(len(result), self.expected_result_length)

    def get_test_query(self):
        raise NotImplementedError


class BenchmarkOriginal(PageQueryBenchmark, TestCase):
    test_description = "Page.objects.specific()"

    def get_test_query(self):
        return Page.objects.filter(depth=3).specific()


class BenchmarkOriginalTypeRestricted(PageQueryBenchmark, TestCase):
    test_description = "Page.objects.exact_type(*types).specific()"

    def get_test_query(self):
        return Page.objects.filter(depth=3).exact_type(*self.page_types).specific()


class BenchmarkOriginalDeferred(PageQueryBenchmark, TestCase):
    test_description = "Page.objects.specific(defer=True)"

    def get_test_query(self):
        return Page.objects.filter(depth=3).specific(defer=True)


class BenchmarkNew(PageQueryBenchmark, TestCase):
    test_description = "Page.objects.specific_new()"

    def get_test_query(self):
        return Page.objects.filter(depth=3).specific_new()


class BenchmarkNewTypeRestricted(PageQueryBenchmark, TestCase):
    test_description = "Page.objects.exact_type(*types).specific_new()"

    def get_test_query(self):
        return Page.objects.filter(depth=3).exact_type(*self.page_types).specific_new()


class BenchmarkNewDeferred(PageQueryBenchmark, TestCase):
    test_description = "Page.objects.specific_new(defer=True)"

    def get_test_query(self):
        return Page.objects.filter(depth=3).specific_new(defer=True)


class BenchmarkNewWithDeferLargeFields(PageQueryBenchmark, TestCase):
    test_description = "Page.objects.defer_large_fields().specific_new()"

    def get_test_query(self):
        return Page.objects.filter(depth=3).defer_large_fields().specific_new()


class BenchmarkNewTypeRestritedWithDeferLargeFields(PageQueryBenchmark, TestCase):
    test_description = "Page.objects.exact_type(*types).defer_large_fields().specific_new()"

    def get_test_query(self):
        return (
            Page.objects.filter(depth=3)
            .exact_type(*self.page_types)
            .defer_large_fields()
            .specific_new()
        )
