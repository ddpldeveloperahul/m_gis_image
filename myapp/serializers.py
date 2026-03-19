from rest_framework import serializers
from django.contrib.auth.models import User
from myapp.models import SpatialJoinResult



# ✅ SIGNUP SERIALIZER
class SignupSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'password']

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data.get('email'),
            password=validated_data['password']
        )
        return user


# ✅ LOGIN SERIALIZER
class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)
    
    
class SpatialJoinResultSerializer(serializers.ModelSerializer):
    excel_url = serializers.SerializerMethodField()

    class Meta:
        model = SpatialJoinResult
        fields = ['id', 'excel_url', 'created_at']

    def get_excel_url(self, obj):
        request = self.context.get('request')
        return request.build_absolute_uri(obj.result_excel.url)