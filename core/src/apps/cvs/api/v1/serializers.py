from rest_framework import serializers


class CvUploadSerializer(serializers.Serializer):
    file = serializers.FileField()


class CvGenerateSerializer(serializers.Serializer):
    instructions = serializers.CharField()
    position_text = serializers.CharField(required=False, allow_blank=True, default="")
    filename = serializers.CharField(required=False, allow_blank=True, default="")


class CvSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    original_filename = serializers.CharField()
    full_name = serializers.CharField()
    email = serializers.CharField()
    phone = serializers.CharField()
    linkedin_url = serializers.CharField()
    git_url = serializers.CharField()
    uploaded_at = serializers.DateTimeField()
