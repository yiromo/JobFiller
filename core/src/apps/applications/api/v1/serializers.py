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


class ScanRequestSerializer(serializers.Serializer):
    url = serializers.URLField(max_length=2048)
    form_snapshot = FormFieldSerializer(many=True)
    cv_id = serializers.IntegerField(required=False, allow_null=True, default=None)


class FieldActionSerializer(serializers.Serializer):
    ref = serializers.CharField()
    value = serializers.CharField(allow_blank=True)
    action = serializers.ChoiceField(choices=["type", "select", "check", "upload", "skip"])
    confidence = serializers.FloatField()


class ScanResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    url = serializers.CharField()
    site = serializers.CharField()
    field_mapping = FieldActionSerializer(many=True)
