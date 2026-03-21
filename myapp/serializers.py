from rest_framework import serializers
from django.contrib.auth.models import User
from myapp.models import SpatialJoinResult



# ✅ SIGNUP SERIALIZER
class SignupSerializer(serializers.ModelSerializer):
    username = serializers.CharField(required=True)
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True, required=True)
    confirm_password = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'password', 'confirm_password']
        extra_kwargs = {
            'username': {'required': True},
            'email': {'required': True},
            'password': {'required': True},
        }

    def validate(self, data):
        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError({
                'confirm_password': 'Password and confirm password do not match.'
            })
        return data

    def create(self, validated_data):
        validated_data.pop('confirm_password')
        return User.objects.create_user(**validated_data)


# ✅ LOGIN SERIALIZER
class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(required=False)
    password = serializers.CharField(write_only=True, required=False)

    def validate(self, data):
        errors = {}

        username = data.get('username') or data.get('usename')
        if not username:
            errors['username'] = ['Username is required.']

        password = data.get('password')
        if not password:
            errors['password'] = ['Password is required.']

        if errors:
            raise serializers.ValidationError(errors)

        data['username'] = username
        return data
    
    
class SpatialJoinResultSerializer(serializers.ModelSerializer):
    excel_url = serializers.SerializerMethodField()

    class Meta:
        model = SpatialJoinResult
        fields = ['id', 'excel_url', 'created_at']

    def get_excel_url(self, obj):
        request = self.context.get('request')
        return request.build_absolute_uri(obj.result_excel.url)