from itertools import chain
from collections import namedtuple

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from django.shortcuts import get_object_or_404

from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.generics import ListAPIView
from rest_framework.viewsets import ViewSet

from accounting.models import Project
from history.models import Standup, Blocker
from history.serializers import ReportSerializer, BlockerSerializer
from utils.mixins import Query, TZ

from .serializers import FeedSerializer, EventSerializer, PendingIssueSerializer
from .models import Event
from .paginations import FeedPagination


class Feed(Query, TZ, ListAPIView):
    """ feed endpoint.
        contains scheduled events, daily report, etc.
    """
    queryset = None
    serializer_class = FeedSerializer
    pagination_class = FeedPagination
    permission_classes = (IsAuthenticated,)

    def get_queryset(self, *args, **kwargs):
        # calculate the 3 month range parameter.
        months_3 = self.last_n_months(1)

        return sorted(chain(
                Standup.objects.filter(user=self.request.user,
                    date_created__range=months_3),
                Event.objects.filter(
                    date_created__range=months_3)
            ),
            key=lambda instance: instance.date_created,
            reverse=True,
        )


class Notification(Query, TZ, ViewSet):
    """ daily notification
    """
    def events(self, *args, **kwargs):
        serializer = EventSerializer(
            Event.objects.triggered_today(),
            many=True
        )
        return Response(serializer.data, status=200)

    def pending(self, *args, **kwargs):
        # filter standups that has blockers that
        # are not yet fixed.
        serializer = BlockerSerializer(
            self._filter(Blocker,
                standup__user=self.request.user,
                is_fixed=False
            ),
            many=True
        )
        return Response(serializer.data, status=200)


    def group_by_project(self, query):
        """ method that will reconstruct the queryset
            and group it by project.
        """
        def _flat(q, key, distinct=False):
            # shorthand (hacky) for transforming query to flat list
            if distinct: return q.values_list(key, flat=True).distinct()
            return q.values_list(key, flat=True)

        def _get_blockers(q, pid):
            return _flat(q.filter(project=pid), 'blocker')

        def _assign(item):
            """ construct the data into an object.
                why object and not dict? because objects are cool!
            """
            return namedtuple(
                "PendingIssue",
                ('project_id', 'blockers')
            )(*item)

        # transform the query based on the project and blocker IDs
        query = query.values('project', 'blocker')
        # get the distinct project list
        projects = _flat(query, 'project', distinct=True)

        # transform and re-group (by project) the query list into a dictionary
        # which will be flatten to become a list of objects.
        rdict = {p:_get_blockers(query, p) for p in projects}

        # transform the dict query into flatten list which will be
        # passed into the serializer for serializing.
        return [_assign(item) for item in rdict.items()]


class Calendar(Query, TZ, ViewSet):
    """ calendar endpoint
    """
    def events(self, *args, **kwargs):
        year = self.request.query_params.get('year', timezone.now().year)
        serializer = EventSerializer(
            Event.objects.on_year(year),
            many=True
        )
        return Response(serializer.data, status=200)

    def create(self, request, *args, **kwargs):
        user = request.user

        serializer = EventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(organizer=user)

        return Response(serializer.data, status=200)
    
    def update(self, request, *args, **kwargs):
        event = get_object_or_404(Event, pk=kwargs.get('pk'))

        serializer = EventSerializer(
            event,
            data=request.data,
            partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data, status=200)

    def remove(self, request, *args, **kwargs):
        event = get_object_or_404(Event, pk=kwargs.get('pk'), organizer=request.user)
        serializer = EventSerializer(event)
        data = serializer.data
        event.delete()
        return Response(data, status=200)