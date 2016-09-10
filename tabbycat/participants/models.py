import logging
from warnings import warn

from django.contrib.contenttypes.fields import GenericRelation
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.functional import cached_property

from tournaments.models import Round
from utils.managers import LookupByNameFieldsMixin

from .emoji import EMOJI_LIST

logger = logging.getLogger(__name__)


class Region(models.Model):
    name = models.CharField(db_index=True, max_length=100)
    tournament = models.ForeignKey('tournaments.Tournament', models.CASCADE)

    def __str__(self):
        return '%s' % (self.name)


class InstitutionManager(LookupByNameFieldsMixin, models.Manager):
    name_fields = ['code', 'name', 'abbreviation']


class Institution(models.Model):
    name = models.CharField(max_length=100,
        help_text="The institution's full name, e.g., \"University of Cambridge\", \"Victoria University of Wellington\"")
    code = models.CharField(max_length=20,
        help_text="What the institution is typically called for short, e.g., \"Cambridge\", \"Vic Wellington\"")
    abbreviation = models.CharField(max_length=8, default="",
        help_text="For extremely confined spaces, e.g., \"Camb\", \"VicWgtn\"")
    region = models.ForeignKey(Region, models.CASCADE, blank=True, null=True)

    objects = InstitutionManager()

    @property
    def venue_preferences(self):
        return self.institutionvenueconstraint_set.all().order_by('-priority')

    class Meta:
        unique_together = [('name', 'code')]
        ordering = ['name']

    def __str__(self):
        return str(self.name)

    @property
    def short_code(self):
        if self.abbreviation:
            return self.abbreviation
        else:
            return self.code[:5]


class Person(models.Model):
    name = models.CharField(max_length=40, db_index=True)
    barcode_id = models.IntegerField(blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=40, blank=True, null=True)
    novice = models.BooleanField(default=False,
        help_text="Novice status is indicated on the tab, and may have its own Break Category or Top Speakers Tab")

    checkin_message = models.TextField(blank=True)
    notes = models.TextField(blank=True, null=True)

    GENDER_MALE = 'M'
    GENDER_FEMALE = 'F'
    GENDER_OTHER = 'O'
    GENDER_CHOICES = ((GENDER_MALE,     'Male'),
                      (GENDER_FEMALE,   'Female'),
                      (GENDER_OTHER,    'Other'))
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES, blank=True, null=True,
        help_text="Gender is displayed in the adjudicator allocation interface, and nowhere else")
    pronoun = models.CharField(max_length=10, blank=True, null=True,
        help_text="If printing ballots using Tabbycat there is the option to pre-print pronouns")

    @property
    def has_contact(self):
        return bool(self.email or self.phone)


class TeamManager(LookupByNameFieldsMixin, models.Manager):
    name_fields = ['short_name', 'long_name']

    def get_queryset(self):
        return super().get_queryset().select_related('institution')


class Team(models.Model):
    reference = models.CharField(blank=True, max_length=150, verbose_name="Full name/suffix",
        help_text="Do not include institution name (see \"uses institutional prefix\" below)")
    short_reference = models.CharField(blank=True, max_length=35, verbose_name="Short name/suffix",
        help_text="The name shown in the draw. Do not include institution name (see \"uses institutional prefix\" below)")

    short_name = models.CharField(editable=False, max_length=50, verbose_name="Short name",
        help_text="The name shown in the draw, including institution name. (This is autogenerated.)")
    long_name = models.CharField(editable=False, max_length=200, verbose_name="Long name",
        help_text="The full name of the team, including institution name. (This is autogenerated.)")

    emoji = models.CharField(max_length=2, blank=True, null=True, choices=EMOJI_LIST)
    institution = models.ForeignKey(Institution, models.CASCADE)
    tournament = models.ForeignKey('tournaments.Tournament', models.CASCADE)
    division = models.ForeignKey('divisions.Division', models.SET_NULL, blank=True, null=True)
    use_institution_prefix = models.BooleanField(default=False, verbose_name="Uses institutional prefix",
        help_text="If ticked, a team called \"1\" from Victoria will be shown as \"Victoria 1\" ")
    url_key = models.SlugField(blank=True, null=True, unique=True, max_length=24)
    break_categories = models.ManyToManyField('breakqual.BreakCategory', blank=True)

    round_availabilities = GenericRelation('availability.RoundAvailability')

    @property
    def venue_preferences(self):
        return self.teamvenuepreference_set.all().order_by('-priority')

    TYPE_NONE = 'N'
    TYPE_SWING = 'S'
    TYPE_COMPOSITE = 'C'
    TYPE_BYE = 'B'
    TYPE_CHOICES = ((TYPE_NONE, 'None'),
                    (TYPE_SWING, 'Swing'),
                    (TYPE_COMPOSITE, 'Composite'),
                    (TYPE_BYE, 'Bye'), )
    type = models.CharField(max_length=1,
                            choices=TYPE_CHOICES,
                            default=TYPE_NONE)

    class Meta:
        unique_together = [('reference', 'institution', 'tournament'),
                           ('emoji', 'tournament')]
        ordering = ['tournament', 'institution', 'short_reference']
        index_together = ['tournament', 'institution', 'short_reference']

    objects = TeamManager()

    def __str__(self):
        return "[{}] {}".format(self.tournament.slug, self.short_name)

    def _construct_short_name(self):
        institution = self.institution
        reference = self.short_reference or self.reference
        if self.use_institution_prefix:
            short_name = institution.code or institution.abbreviation
            if reference:
                short_name += " " + reference
            return short_name
        else:
            return reference

    def _construct_long_name(self):
        institution = self.institution
        if self.use_institution_prefix:
            long_name = institution.name
            if self.reference:
                long_name += " " + self.reference
            return long_name
        else:
            return self.reference

    @property
    def region(self):
        return self.get_cached_institution().region

    @property
    def break_categories_nongeneral(self):
        return self.break_categories.exclude(is_general=True)

    @property
    def break_categories_str(self):
        categories = self.break_categories_nongeneral
        return ", ".join(c.name for c in categories) if categories else ""

    def break_rank_for_category(self, category):
        from breakqual.models import BreakingTeam
        bt = BreakingTeam.objects.get(break_category=category, team=self)
        return bt.break_rank

    def get_aff_count(self, seq=None):
        from draw.models import DebateTeam
        return self._get_count(DebateTeam.POSITION_AFFIRMATIVE, seq)

    def get_neg_count(self, seq=None):
        from draw.models import DebateTeam
        return self._get_count(DebateTeam.POSITION_NEGATIVE, seq)

    def _get_count(self, position, seq):
        dts = self.debateteam_set.filter(
            position=position,
            debate__round__stage=Round.STAGE_PRELIMINARY)
        if seq is not None:
            dts = dts.filter(debate__round__seq__lte=seq)
        return dts.count()

    def get_debates(self, before_round):
        dts = self.debateteam_set.select_related('debate').order_by(
            'debate__round__seq')
        if before_round is not None:
            dts = dts.filter(debate__round__seq__lt=before_round)
        return [dt.debate for dt in dts]

    @property
    def debates(self):
        return self.get_debates(None)

    @property
    def wins_count(self):
        try:
            return self._wins_count
        except AttributeError:
            from results.models import TeamScore
            self._wins_count = TeamScore.objects.filter(ballot_submission__confirmed=True,
                                            debate_team__team=self,
                                            win=True).count()
            return self._wins_count

    @cached_property
    def speakers(self):
        return self.speaker_set.all()

    def seen(self, other, before_round=None):
        queryset = self.debateteam_set.filter(debate__debateteam__team=other)
        if before_round:
            queryset = queryset.filter(debate__round__seq__lt=before_round)
        return queryset.count()

    def same_institution(self, other):
        return self.institution_id == other.institution_id

    def prev_debate(self, round_seq):
        from draw.models import DebateTeam
        try:
            return DebateTeam.objects.filter(
                debate__round__seq__lt=round_seq,
                team=self, ).order_by('-debate__round__seq')[0].debate
        except IndexError:
            return None

    def get_cached_institution(self):
        cached_key = "%s_%s_%s" % ('teamid', self.id, '_institution__object')
        cached_value = cache.get(cached_key)
        if cached_value:
            return cache.get(cached_key)
        else:
            cached_value = self.institution
            cache.set(cached_key, cached_value, None)
            return cached_value

    def clean(self):
        # Require reference and short_reference if use_institution_prefix is False
        errors = {}
        if not self.use_institution_prefix and not self.reference:
            errors['reference'] = "Teams must have a full name if they don't use the institutional prefix."
        if not self.use_institution_prefix and not self.short_reference:
            errors['short_reference'] = "Teams must have a short name if they don't use the institutional prefix."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        # Override the short and long names before saving
        self.short_name = self._construct_short_name()
        self.long_name = self._construct_long_name()
        super().save(*args, **kwargs)


class Speaker(Person):
    team = models.ForeignKey(Team, models.CASCADE)

    def __str__(self):
        return str(self.name)


class AdjudicatorManager(models.Manager):
    use_for_related_fields = True

    def get_queryset(self):
        return super(AdjudicatorManager, self).get_queryset().select_related('institution')


class Adjudicator(Person):
    institution = models.ForeignKey(Institution, models.CASCADE)
    tournament = models.ForeignKey('tournaments.Tournament', models.CASCADE, blank=True, null=True,
        help_text="Adjudicators not assigned to any tournament can be shared between tournaments")
    test_score = models.FloatField(default=0)
    url_key = models.SlugField(blank=True, null=True, unique=True, max_length=24)

    institution_conflicts = models.ManyToManyField('Institution',
        through='adjallocation.AdjudicatorInstitutionConflict',
        related_name='adj_inst_conflicts')
    conflicts = models.ManyToManyField('Team',
        through='adjallocation.AdjudicatorConflict',
        related_name='adj_adj_conflicts')

    breaking = models.BooleanField(default=False)
    independent = models.BooleanField(default=False, blank=True)
    adj_core = models.BooleanField(default=False, blank=True)

    round_availabilities = GenericRelation('availability.RoundAvailability')

    objects = AdjudicatorManager()

    class Meta:
        ordering = ['tournament', 'institution', 'name']

    def __str__(self):
        return "%s (%s)" % (self.name, self.institution.code)

    def conflict_with(self, team):
        if not hasattr(self, '_conflict_cache'):
            from adjallocation.models import AdjudicatorConflict, AdjudicatorInstitutionConflict
            self._conflict_cache = set(
                c['team_id']
                for c in AdjudicatorConflict.objects.filter(
                    adjudicator=self).values('team_id'))
            self._institution_conflict_cache = set(
                c['institution_id']
                for c in AdjudicatorInstitutionConflict.objects.filter(
                    adjudicator=self).values('institution_id'))
        return team.id in self._conflict_cache or team.institution_id in self._institution_conflict_cache

    @property
    def is_unaccredited(self):
        return self.novice

    @property
    def region(self):
        return self.institution.region

    def weighted_score(self, feedback_weight):
        feedback_score = self._feedback_score()
        if feedback_score is None:
            feedback_score = 0
            feedback_weight = 0
        return self.test_score * (1 - feedback_weight) + (feedback_weight * feedback_score)

    @cached_property
    def score(self):
        warn("Adjudicator.score is inefficient; consider using Adjudicator.weighted_score() instead.", stacklevel=2)
        if self.tournament:
            weight = self.tournament.current_round.feedback_weight
        else:
            weight = 1  # For shared ajudicators
        return self.weighted_score(weight)

    def _feedback_score(self):
        try:
            return self._feedback_score_cache
        except AttributeError:
            from adjallocation.models import DebateAdjudicator
            self._feedback_score_cache = self.adjudicatorfeedback_set.filter(confirmed=True).exclude(
                source_adjudicator__type=DebateAdjudicator.TYPE_TRAINEE).aggregate(
                    avg=models.Avg('score'))['avg']
            return self._feedback_score_cache

    @property
    def feedback_score(self):
        return self._feedback_score() or None

    def get_feedback(self):
        return self.adjudicatorfeedback_set.all()

    def seen_team(self, team, before_round=None):
        from draw.models import DebateTeam
        if not hasattr(self, '_seen_cache'):
            self._seen_cache = {}
        if before_round not in self._seen_cache:
            qs = DebateTeam.objects.filter(
                debate__debateadjudicator__adjudicator=self)
            if before_round is not None:
                qs = qs.filter(debate__round__seq__lt=before_round.seq)
            self._seen_cache[before_round] = set(dt.team.id for dt in qs)
        return team.id in self._seen_cache[before_round]

    def seen_adjudicator(self, adj, before_round=None):
        from adjallocation.models import DebateAdjudicator
        d = DebateAdjudicator.objects.filter(
            adjudicator=self,
            allocations__debateadjudicator__adjudicator=adj, )
        if before_round is not None:
            d = d.filter(debate__round__seq__lt=before_round.seq)
        return d.count()
