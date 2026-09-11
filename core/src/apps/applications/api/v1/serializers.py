from rest_framework import serializers


class FormFieldSerializer(serializers.Serializer):
    ref = serializers.CharField()
    tag = serializers.CharField()
    type = serializers.CharField(required=False, allow_blank=True, default="")
    name = serializers.CharField(required=False, allow_blank=True, default="")
    id = serializers.CharField(required=False, allow_blank=True, default="")
    label = serializers.CharField(required=False, allow_blank=True, default="")
    placeholder = serializers.CharField(required=False, allow_blank=True, default="")
    options = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    required = serializers.BooleanField(required=False, default=False)
    role = serializers.CharField(required=False, allow_blank=True, default="")
    aria_haspopup = serializers.CharField(required=False, allow_blank=True, default="")
    aria_controls = serializers.CharField(required=False, allow_blank=True, default="")


class EeoAnswerSerializer(serializers.Serializer):
    match = serializers.CharField()
    answer = serializers.CharField(allow_blank=True)


class ScanRequestSerializer(serializers.Serializer):
    url = serializers.URLField(max_length=2048)
    form_snapshot = FormFieldSerializer(many=True)
    cv_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    page_text = serializers.CharField(required=False, allow_blank=True, default="")
    about_text = serializers.CharField(required=False, allow_blank=True, default="")
    eeo_answers = EeoAnswerSerializer(many=True, required=False, default=list)


class FileAttachmentSerializer(serializers.Serializer):
    filename = serializers.CharField()
    mime_type = serializers.CharField()
    base64 = serializers.CharField()


class FieldActionSerializer(serializers.Serializer):
    ref = serializers.CharField()
    value = serializers.CharField(allow_blank=True)
    action = serializers.ChoiceField(choices=["type", "select", "check", "upload", "skip"])
    confidence = serializers.FloatField()
    # Present only for a generated cover letter's "upload" action — the extension
    # attaches these bytes directly instead of fetching a stored CV by `value`.
    file = FileAttachmentSerializer(required=False, allow_null=True)


class ScanResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    url = serializers.CharField()
    site = serializers.CharField()
    field_mapping = FieldActionSerializer(many=True)


class GenerateCoverLetterRequestSerializer(serializers.Serializer):
    application_id = serializers.IntegerField()
    page_text = serializers.CharField(required=False, allow_blank=True, default="")
    about_text = serializers.CharField(required=False, allow_blank=True, default="")


class GenerateCoverLetterResponseSerializer(serializers.Serializer):
    text = serializers.CharField()
    entries = FieldActionSerializer(many=True)
