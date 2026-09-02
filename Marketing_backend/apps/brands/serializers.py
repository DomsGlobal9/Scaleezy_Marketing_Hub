from rest_framework import serializers

from .models import Brand


class BrandSerializer(serializers.ModelSerializer):
    has_logo = serializers.BooleanField(read_only=True)

    class Meta:
        model = Brand
        fields = '__all__'
        # `workspace` is assigned server-side from the authorised request. A
        # client-writable workspace is exactly how the Phase 1c audit found
        # cross-tenant writes on the other viewsets.
        read_only_fields = [
            'id',
            'workspace',
            'logo_url',
            'logo_storage_path',
            'logo_file_name',
            'created_by',
            'created_at',
            'updated_at',
            # Approval is Scaleezy's decision, recorded by the approval
            # service; a client must not be able to write who approved them.
            'reviewed_at',
            'reviewed_by',
        ]

    def validate_status(self, value):
        """A client may archive and restore its own approved brands, as before.

        It may not leave PENDING: that transition is approval, and it belongs to
        the approval service (apps.brands.services.approval), not to a PATCH
        on the brand. Nor may it put a brand INTO pending — signup does that.
        """
        current = self.instance.status if self.instance is not None else None
        if current == Brand.Status.PENDING and value != Brand.Status.PENDING:
            raise serializers.ValidationError(
                "This brand is awaiting Scaleezy approval; its status cannot be changed here."
            )
        if value == Brand.Status.PENDING and current != Brand.Status.PENDING:
            raise serializers.ValidationError(
                "Pending approval is set at signup, not by editing a brand."
            )
        if self.instance is not None and value != current:
            workspace = self.instance.workspace
            # Only an approved client may archive and restore its brands. A
            # rejected client's brand was archived BY Scaleezy; un-archiving it
            # is not theirs to do, and a pending client has nothing to restore.
            if not workspace.is_approved:
                raise serializers.ValidationError(
                    "This client is not approved; brand status cannot be changed here."
                )
        return value

    def validate_palette(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Palette must be an object of colour roles.")
        return value

    def validate_fonts(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Fonts must be an object.")
        return value

    def validate_competitors(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Competitors must be a list.")
        return value

    def validate_creative_brain(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("creative_brain must be an object.")
        return value

    def validate_products_services(self, value):
        """A list of {name, description}, and nothing else.

        Returns a rebuilt list rather than the submitted one: a JSONField keeps
        whatever it is given forever, so an unrecognised key would be stored
        for the life of the brand and never rendered by anything.
        """
        if not isinstance(value, list):
            raise serializers.ValidationError(
                "Products and services must be a list of {name, description} objects."
            )

        cleaned = []
        for entry in value:
            if not isinstance(entry, dict):
                raise serializers.ValidationError(
                    "Each product or service must be an object with a name and a description."
                )
            name = entry.get('name')
            if not isinstance(name, str) or not name.strip():
                raise serializers.ValidationError("Each product or service needs a name.")
            description = entry.get('description', '')
            if not isinstance(description, str):
                raise serializers.ValidationError(
                    "A product or service description must be text."
                )
            cleaned.append({'name': name.strip(), 'description': description.strip()})
        return cleaned

    def validate_guardrails(self, value):
        """Stored canonical: lists of trimmed unique strings, known keys only.

        Rebuilt rather than accepted — a JSONField keeps whatever it is given
        forever, and guardrails are read on every single generation. Limits
        are refused loudly, not trimmed silently: a rule the founder typed
        that quietly vanished would be worse than an error message."""
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                "Guardrails must be an object of rule lists."
            )
        from .services import guardrails as guardrail_law

        for key in guardrail_law.LIST_KEYS:
            items = value.get(key)
            if not isinstance(items, list):
                continue
            if len(items) > guardrail_law.MAX_ITEMS:
                raise serializers.ValidationError(
                    f"Too many rules in {key.replace('_', ' ')} — "
                    f"the limit is {guardrail_law.MAX_ITEMS}."
                )
            for item in items:
                if isinstance(item, str) and len(item.strip()) > guardrail_law.MAX_TERM_LENGTH:
                    raise serializers.ValidationError(
                        f"A rule in {key.replace('_', ' ')} is longer than "
                        f"{guardrail_law.MAX_TERM_LENGTH} characters — shorten it."
                    )
        return guardrail_law.clean(value)

    def validate_social_links(self, value):
        """{platform: url}. One flat level, strings only.

        A nested object here would reach the compiled brain and then a prompt as
        an unreadable blob, so it is refused at the door instead.
        """
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                "Social links must be an object of platform to URL."
            )
        for platform, url in value.items():
            if not isinstance(platform, str) or not platform.strip():
                raise serializers.ValidationError("Each social link needs a platform name.")
            if not isinstance(url, str):
                raise serializers.ValidationError(
                    f"The {platform} link must be a URL string."
                )
        return {platform.strip(): url.strip() for platform, url in value.items()}


class BrandLogoUploadSerializer(serializers.Serializer):
    file = serializers.ImageField()
