import math

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from utils.models import UniqueConstraint


class BreakCategory(models.Model):
    tournament = models.ForeignKey('tournaments.Tournament', models.CASCADE,
        verbose_name=_("tournament"))
    name = models.CharField(max_length=50,
        verbose_name=_("name"),
        help_text=_("Name to be displayed, e.g., \"ESL\""))
    slug = models.SlugField(
        verbose_name=_("slug"),
        help_text=_("Slug for URLs, e.g., \"esl\""))
    seq = models.IntegerField(
        verbose_name=_("sequence number"),
        help_text=_("The order in which the categories are displayed"))
    break_size = models.IntegerField(validators=[MinValueValidator(2)],
                                     verbose_name=_("break size"),
                                     help_text=_("Number of breaking teams in this category"))
    reserve_size = models.PositiveIntegerField(default=0, verbose_name=_("Reserve size"),
                                       help_text=_("Number of reserve teams in this category."))
    is_general = models.BooleanField(
        verbose_name=_("is general"),
        help_text=_("Are teams eligible for this break by default"))
    priority = models.IntegerField(
        verbose_name=_("priority"),
        help_text=_("If a team breaks in multiple categories, higher priority "
            "numbers take precedence; teams can break into multiple categories "
            "if and only if they all have the same priority"))
    limit = models.IntegerField(default=0,
        verbose_name=_("limit"),
        help_text=_("At most this many teams will be shown on the public tab for this category, or use 0 for no limit"))

    BREAK_QUALIFICATION_CHOICES = [
        ('standard', _("Standard")),
        ('aida-1996', _("AIDA 1996")),
        ('aida-2016-easters', _("AIDA 2016 (Easters)")),
        ('aida-2016-australs', _("AIDA 2016 (Australs)")),
        ('aida-2019-australs-open', _("AIDA 2019 (Australs, Dynamic Cap)")),
    ]

    rule = models.CharField(max_length=25, choices=BREAK_QUALIFICATION_CHOICES, default='standard',
        verbose_name=_("rule"),
        help_text=_("Rule for how the break is calculated (most tournaments should use \"Standard\")"))

    breaking_teams = models.ManyToManyField('participants.Team', through='BreakingTeam',
        verbose_name=_("breaking teams"))

    def __str__(self):
        return "[{}] {}".format(self.tournament.slug, self.name)

    class Meta:
        constraints = [
            UniqueConstraint(fields=['tournament', 'seq']),
            UniqueConstraint(fields=['tournament', 'slug']),
        ]
        ordering = ['tournament', 'seq']
        verbose_name = _("break category")
        verbose_name_plural = _("break categories")

    @property
    def breakingteam_set_competing(self):
        """Returns a QuerySet of BreakingTeam instances representing teams who
        will actually compete in the elimination round series."""
        return self.breakingteam_set.filter(break_rank__isnull=False)

    @property
    def num_break_rounds(self):
        if self.tournament.pref('teams_in_debate') == 4:
            return math.ceil(math.log2(self.break_size / 2))
        else:
            return math.ceil(math.log2(self.break_size))


class BreakingTeam(models.Model):
    break_category = models.ForeignKey(BreakCategory, models.CASCADE,
        verbose_name=_("break category"))
    team = models.ForeignKey('participants.Team', models.CASCADE,
        verbose_name=_("team"))
    rank = models.IntegerField(
        verbose_name=_("rank"))
    break_rank = models.IntegerField(blank=True, null=True,
        verbose_name=_("break rank"))

    class Remark(models.TextChoices):
        CAPPED = 'C', _("Capped")
        INELIGIBLE = 'I', _("Ineligible")
        DIFFERENT_BREAK = 'D', _("Different break")
        DISQUALIFIED = 'd', _("Disqualified")
        LOST_COIN_TOSS = 't', _("Lost coin toss")
        WITHDRAWN = 'w', _("Withdrawn")
        RESERVE = 'R', _("Reserve")
        ABSENT = 'A', _("Absent")

    remark = models.CharField(max_length=1, choices=Remark.choices, blank=True, null=True,
        verbose_name=_("remark"),
        help_text=_("Used to explain why an otherwise-qualified team didn't break"))

    class Meta:
        constraints = [UniqueConstraint(fields=['break_category', 'team'])]
        verbose_name = _("breaking team")
        verbose_name_plural = _("breaking teams")
